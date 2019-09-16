#!/usr/bin/env python

import argparse
import datetime
import difflib
import inspect
import os
import plistlib
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pwd import getpwuid

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
try:
    from shlex import quote as cmd_quote
except ImportError:
    # https://stackoverflow.com/questions/26790916/python-3-backward-compatability-shlex-quote-vs-pipes-quote#26791164
    from pipes import quote as cmd_quote
try:
    from queue import Empty as QueueEmpty
    from queue import Queue
except ImportError:
    from Queue import Empty as QueueEmpty
    from Queue import Queue

from .version import PrefsniffAbout

STARS="*****************************"

def parse_args(argv):
    parser=argparse.ArgumentParser()
    parser.add_argument("watchpath",help="Directory or plist file to watch for changes.")
    parser.add_argument(
        "--version",
        help="Show version and exit.",
        action='version',
        version=str(PrefsniffAbout()))
    parser.add_argument("--show-diffs",help="Show diff of changed plist files.",action="store_true")
    args=parser.parse_args(argv)
    return args


def deserialize_plist(data):
    if sys.version_info >= (3, 4):
        return plistlib.loads(data)
    else:
        if data.startswith(b'bplist'):
            with tempfile.NamedTemporaryFile() as f:
                f.write(data)
                f.flush()
                data = subprocess.check_output(
                    ["plutil", "-convert", "xml1", "-o", "-", f.name])
        return plistlib.readPlistFromString(data)


def serialize_plist(data):
    if sys.version_info >= (3, 4):
        return plistlib.dumps(data, fmt=plistlib.FMT_XML).decode('utf-8')
    else:
        return plistlib.writePlistToString(data)


class PSniffException(Exception):
    pass

class PSChangeTypeException(PSniffException):
    pass
class PSChangeTypeNotImplementedException(PSChangeTypeException):
    pass

class PSChangeTypeString(object):


    def __init__(self, domain, byhost, key, value=None):
        self.action = "write"
        self.domain = domain
        self.key = key
        self.type = "-string"
        self.value = value
        self.byhost=byhost

    def __str__(self):
        # defaults action domain key
        command=['defaults']
        if self.byhost:
            command.append('-currentHost')

        command.append(cmd_quote(self.action))
        command.append(cmd_quote(self.domain))
        command.append(cmd_quote(self.key))

        # some commands work without a type and are easier that way
        if self.type is not None:
            command.append(cmd_quote(self.type))
        if self.value is not None:
            if isinstance(self.value, (list, tuple)):
                command.extend(cmd_quote(x) for x in self.value)
            else:
                #print(repr(self.value))
                command.append(cmd_quote(self.value))
        return ' '.join(command)


class PSChangeTypeKeyDeleted(PSChangeTypeString):

    def __init__(self, domain, byhost, key):
        super(PSChangeTypeKeyDeleted, self).__init__(domain, byhost, key, value=None)
        self.action = "delete"
        self.type = None


class PSChangeTypeFloat(PSChangeTypeString):

    def __init__(self, domain,byhost, key, value):
        super(PSChangeTypeFloat, self).__init__(domain, byhost, key)
        self.type = "-float"
        if not isinstance(value, float):
            raise PSChangeTypeException("Float required for -float prefs change.")
        self.value = str(value)


class PSChangeTypeInt(PSChangeTypeString):

    def __init__(self, domain,byhost, key, value):
        super(PSChangeTypeInt, self).__init__(domain, byhost, key)
        self.type = "-int"
        if not isinstance(value, int):
            raise PSChangeTypeException("Integer required for -int prefs change.")
        self.value = str(value)


class PSChangeTypeBool(PSChangeTypeString):

    def __init__(self, domain, byhost, key, value):
        super(PSChangeTypeBool, self).__init__(domain, byhost, key)
        self.type = "-bool"
        if not isinstance(value, bool):
            raise PSChangeTypeException("Boolean required for -bool prefs change.")
        self.value = str(value)


class PSChangeTypeDict(PSChangeTypeString):

    def __init__(self, domain, byhost, key, value={}):
        super(PSChangeTypeDict, self).__init__(domain, byhost, key)
        # We have to omit the -dict type
        # And just let defaults interpet the xml dict string
        self.type = None
        # TODO: not sure what to do here. I want to sanity check we got handed a dict
        # unless we've been subclassed.
        self.value = value
        if isinstance(value, dict):
            self.value = self.to_xmlfrag(value)


    def to_xmlfrag(self, value):

        # create plist-serialized form of changed objects
        plist_str = serialize_plist(value)

        # remove newlines and tabs from plist
        plist_str = "".join([line.strip() for line in plist_str.splitlines()])
        # parse the plist xml doc, so we can pull out the important parts.
        tree = ET.ElementTree(ET.fromstring(plist_str))
        # get elements inside <plist> </plist>
        children = list(tree.getroot())
        # there can only be one element inside <plist>
        if len(children) < 1:
            fn=inspect.getframeinfo(inspect.currentframe()).function
            raise PSChangeTypeException("%s: Empty dictionary for key %s" % (fn,str(self.key)))
        if len(children) > 1:
            fn=inspect.getframeinfo(inspect.currentframe()).function
            raise PSChangeTypeException(
                "%s: Something went wrong for key %s. Can only support one dictionary for dict change." % (fn,self.dict_key))
        # extract changed objects out of the plist element
        # python 2 & 3 compat
        #https://stackoverflow.com/questions/15304229/convert-python-elementtree-to-string#15304351
        xmlfrag = ET.tostring(children[0]).decode()
        return xmlfrag

class PSChangeTypeArray(PSChangeTypeDict):
    def __init__(self, domain, byhost, key, value):
        super(PSChangeTypeArray,self).__init__(domain, byhost, key)
        if not isinstance(value,list):
            raise PSChangeTypeException("PSChangeTypeArray requires a list value type.")
        self.type=None
        self.value=self.to_xmlfrag(value)


class PSChangeTypeDictAdd(PSChangeTypeDict):

    def __init__(self, domain, byhost, key, subkey, value):
        super(PSChangeTypeDictAdd, self).__init__(domain, byhost, key)
        self.type = "-dict-add"
        self.subkey = subkey
        self.value = self.__generate_value_string(subkey, value)

    def __generate_value_string(self, subkey, value):
        xmlfrag = self.to_xmlfrag(value)
        return (subkey, xmlfrag)


    # def __str__(self):
    #     # hopefully generate something like:
    #     #"dict-key 'val-to-add-to-dict'"
    #     # so we can generate a command like
    #     # defaults write foo -dict-add dict-key 'value'
    #     xmlfrag = self.xmlfrag
    #     return " %s '%s'" % (self.dict_key, xmlfrag)

class PSChangeTypeArrayAdd(PSChangeTypeArray):
    def __init__(self, domain, key, byhost, value):
        super(PSChangeTypeArrayAdd,self).__init__(domain, byhost, key, value)
        self.type="-array-add"
        self.value=self.__generate_value_string(value)

    def __generate_value_string(self,value):
        values = []
        for v in value:
            values.append(self.to_xmlfrag(v))
        return values

class PSChangeTypeData(PSChangeTypeString):
    def __init__(self,domain, byhost, key,value):
        raise PSChangeTypeNotImplementedException("%s not implemented" % self.__class__.__name__)

class PSChangeTypeDate(PSChangeTypeString):
    def __init__(self, domain, byhost, key,value):
        raise PSChangeTypeNotImplementedException("%s not implemented" % self.__class__.__name__)


class PrefSniff(object):
    CHANGE_TYPES = {int: PSChangeTypeInt,
                    float: PSChangeTypeFloat,
                    str: PSChangeTypeString,
                    bool: PSChangeTypeBool,
                    dict: PSChangeTypeDict,
                    list: PSChangeTypeArray,
                    plistlib.Data: PSChangeTypeData,
                    datetime.datetime: PSChangeTypeDate}
    
    @classmethod
    def is_nsglobaldomain(cls,plistpath):
        nsglobaldomain=False
        base=os.path.basename(plistpath)
        if base.startswith(".GlobalPreferences"):
            nsglobaldomain=True

        return nsglobaldomain


    @classmethod
    def is_byhost(cls,plistpath):
        byhost=False
        dirname=os.path.dirname(plistpath)
        immediate_parent=os.path.basename(dirname)
        if "ByHost" == immediate_parent:
            byhost=True

        return byhost

    @classmethod
    def is_root_owned(cls,plistpath):
         return getpwuid(os.stat(plistpath).st_uid).pw_name=='root'

    @classmethod
    def getdomain(cls,plistpath,byhost=False):
        domain=None
        globaldomain=cls.is_nsglobaldomain(plistpath)
        root_owned=cls.is_root_owned(plistpath)

        #if root owned (like in /Library/Preferences), need to specify fully qualified
        # literal filename rather than a namespace
        if root_owned:
            domain=plistpath
        elif globaldomain:
            domain="NSGlobalDomain"
        elif byhost:
            #e.g.,
            # '~/Library/Preferences/ByHost/com.apple.windowserver.000E4DFD-62C8-5DC5-A2A4-42AFE04AAB87.plist
            #get just the filename
            base=os.path.basename(plistpath)
            #strip off .plist
            base=os.path.splitext(base)[0]
            #strip off UUID, leaving e.g., com.apple.windowserver
            domain=os.path.splitext(base)[0]
        else:
            base=os.path.basename(plistpath)
            domain=os.path.splitext(base)[0]

        return domain

    def __init__(self, plistpath):
        self.plist_dir = os.path.dirname(plistpath)
        self.plist_base = os.path.basename(plistpath)
        self.byhost=self.is_byhost(plistpath)
        self.pref_domain = self.getdomain(plistpath,byhost=self.byhost)
        

        self.plistpath = plistpath

        # Read the preference file before it changed
        with open(plistpath, 'rb') as f:
            pref1 = deserialize_plist(f.read())

        self._wait_for_prefchange()

        # Read the preference file after it changed
        with open(plistpath, 'rb') as f:
            pref2 = deserialize_plist(f.read())

        added, removed, modified, same = self._dict_compare(pref1, pref2)
        self.removed = {}
        self.added = {}
        self.modified = {}

        # At this stage, added and removed would be
        # a key:value added or removed from the top-level
        #<dict> of the plist
        if len(added):
            self.added = added
        if len(removed):
            self.removed = removed
        if len(modified):
            self.modified = modified

        self.commands = self._generate_commands()
        self.diff = self._unified_diff(pref1, pref2, plistpath)

    def _dict_compare(self, d1, d2):
        d1_keys = set(d1.keys())
        d2_keys = set(d2.keys())
        intersect_keys = d1_keys.intersection(d2_keys)
        added_keys = d2_keys - d1_keys
        added = {o: d2[o] for o in added_keys}
        removed = d1_keys - d2_keys
        modified = {o: (d1[o], d2[o])
                    for o in intersect_keys if d1[o] != d2[o]}
        
        same = set(o for o in intersect_keys if d1[o] == d2[o])
        return added, removed, modified, same

    def _list_compare(self,list1,list2):
        list_diffs={"same":False,"append_to_l1":None,"subtract_from_l1":None}
        if list1==list2:
            list_diffs["same"]=True
            return list_diffs
        if len(list2) > len(list1):
            if list1==list2[:len(list1)]:
                list_diffs["append_to_l1"]=list2[len(list1):]

            return list_diffs
        elif len(list1)>len(list2):
            if list2==list1[:len(list2)]:
                list_diffs["subtract_from_l1"]=list1[len(list2):]
            
            return list_diffs

        return list_diffs



    def _unified_diff(self, frompref, topref, path):
        # Convert both preferences to XML format
        fromxml, toxml = serialize_plist(frompref), serialize_plist(topref)
        fromlines, tolines = fromxml.splitlines(), toxml.splitlines()
        return difflib.unified_diff(fromlines, tolines, path, path)

    def _wait_for_prefchange(self):
        event_queue = Queue()
        event_handler = PrefChangedEventHandler(self.plist_base, event_queue)
        observer = Observer()
        observer.schedule(event_handler, self.plist_dir, recursive=False)
        observer.start()
        pref_updated = False
        try:
            while not pref_updated:
                try:
                    event = event_queue.get(True, 0.5)
                    if event[0] == "moved" and os.path.basename(event[1].dest_path) == self.plist_base:
                        pref_updated = True
                    if event[0] == "modified" and os.path.basename(event[1].src_path) == self.plist_base:
                        pref_updated = True
                    if event[0] == "created" and os.path.basename(event[1].src_path) == self.plist_base:
                        pref_updated = True
                except QueueEmpty:
                    pass
        except KeyboardInterrupt:
            observer.stop()
            raise
        observer.stop()
        observer.join()

    def _change_type_lookup(self, cls):
        try:
            change_type = self.CHANGE_TYPES[cls]
        except (KeyError, TypeError):
            change_type = self._change_type_slow_search(cls)

        return change_type

    def _change_type_slow_search(self, cls):
        for base, change_type in self.CHANGE_TYPES.items():
            if issubclass(cls, base):
                return change_type

        return None

    def _generate_commands(self):
        commands = []
        # sub-dictionaries that must be rewritten because
        # something was removed.
        rewrite_dictionaries = {}

        #we can only append to existing arrays
        #if an array changes in any other way, we have to rewrite it 
        rewrite_lists={}
        domain = self.pref_domain
        for k, v in self.added.items():
            #pprint(v)
            change_type = self._change_type_lookup(v.__class__)
            if not change_type:
                print(v.__class__)
            try:
                change = change_type(domain, self.byhost, k, v)
            except PSChangeTypeNotImplementedException as e:
                change = ("key: %s, %s" % (k,str(e)) )
            commands.append(str(change))

        for k in self.removed:
            change = PSChangeTypeKeyDeleted(domain, self.byhost, k)
            commands.append(str(change))
        for key, val in self.modified.items():
            if isinstance(val[1], dict):
                added, removed, modified, same = self._dict_compare(val[0], val[1])
                if len(removed):
                    # There is no -dict-delete so we have to
                    # rewrite this sub-dictionary
                    rewrite_dictionaries[key] = val[1]
                    continue
                for subkey, subval in added.items():
                    change = PSChangeTypeDictAdd(domain, self.byhost, key, subkey, subval)
                    commands.append(str(change))
                for subkey, subval_tuple in modified.items():
                    change = PSChangeTypeDictAdd(
                        domain, self.byhost, key, subkey, subval_tuple[1])
                    commands.append(str(change))
            elif isinstance(val[1],list):
                list_diffs=self._list_compare(val[0],val[1])
                if list_diffs["same"]:
                    continue
                elif list_diffs["append_to_l1"]:
                    append=list_diffs["append_to_l1"]
                    change=PSChangeTypeArrayAdd(domain,key,append)
                    commands.append(str(change))
                else:
                    rewrite_lists[key]=val[1]
            else:
                # for modified keys that aren't dictionaries, we treat them
                # like adds
                change_type = self._change_type_lookup(val[1].__class__)
                try:
                    change = change_type(domain, self.byhost, key, val[1])
                except PSChangeTypeNotImplementedException as e:
                    change=("key: %s, %s" % (k,str(e)) )
                commands.append(str(change))

        for key, val in rewrite_dictionaries.items():
            change = PSChangeTypeDict(domain, self.byhost, key, val)
            commands.append(str(change))

        for key, val in rewrite_lists.items():
            change = PSChangeTypeArray(domain, self.byhost, key, val)
            commands.append(str(change))

        return commands

    def execute(self, args, stdout=None):
        subprocess.check_call(args, stdout=stdout)


class PrefsWatcher(object):

    def __init__(self, prefsdir):
        self.prefsdir = prefsdir
        self._watch_prefsdir()

    def _watch_prefsdir(self):
        event_queue = Queue()
        event_handler = PrefChangedEventHandler(None, event_queue)
        observer = Observer()
        observer.schedule(event_handler, self.prefsdir, recursive=False)
        observer.start()
        while True:
            try:
                changed=event_queue.get(True, 0.5)
                print("Detected change: [%s] %s" % (changed[0],changed[1].src_path))
            except QueueEmpty:
                pass
            except KeyboardInterrupt:
                break
        observer.stop()
        observer.join()


class PrefChangedEventHandler(FileSystemEventHandler):

    def __init__(self, file_base_name, event_queue):
        super(self.__class__, self).__init__()
        if file_base_name == None:
            file_base_name = ""
        self.file_base_name = file_base_name
        self.event_queue = event_queue
        print("Watching prefs file: %s" % self.file_base_name)

    def on_created(self, event):
        if not self.file_base_name in os.path.basename(event.src_path):
            return
        self.event_queue.put(("created", event))

    def on_deleted(self, event):
        if not self.file_base_name in os.path.basename(event.src_path):
            return
        self.event_queue.put(("deleted", event))

    def on_modified(self, event):
        if not self.file_base_name in os.path.basename(event.src_path):
            return
        self.event_queue.put(("modified", event))

    def on_moved(self, event):
        if not self.file_base_name in os.path.basename(event.src_path):
            return
        self.event_queue.put(("moved", event))





def test_dict_add(domain, key, subkey, value):
    prefchange = PSChangeTypeDictAdd(domain, key, subkey, value)
    print(str(prefchange))


def test_dict_add_dict(args):
    domain = args[0]
    key = args[1]
    subkey = args[2]
    value = {"mykey1": 2.0, "mykey2": 7}
    test_dict_add(domain, key, subkey, value)


def test_dict_add_float(args):
    domain = args[0]
    key = args[1]
    subkey = args[2]
    value = 2.0
    test_dict_add(domain, key, subkey, value)


def test_write_dict(args):
    domain = args[0]
    key = args[1]
    value = {"dictkey1": 2.0, "dictkey2": {"subkey": '7'}}
    prefchange = PSChangeTypeDict(domain, key, value)
    print(str(prefchange))

def parse_test_args(argv):
    if "test-dict-add-float" == argv[1]:
        test_dict_add_float(argv[2:])
        exit(0)

    if "test-dict-add-dict" == argv[1]:
        test_dict_add_dict(argv[2:])
        exit(0)

    if "test-write-dict" == argv[1]:
        test_write_dict(argv[2:])
        exit(0)


def main(argv):
    args = parse_args(sys.argv[1:])
    monitor_dir_events=False
    show_diffs=False

    plistpath=args.watchpath
    if os.path.isdir(plistpath):
        monitor_dir_events=True
    elif not os.path.isfile(plistpath):
        print("Error: %s is not a directory or file, or does not exist." % plistpath)
        exit(1)

    if args.show_diffs:
        show_diffs=True
    print("{} version {}".format(PrefsniffAbout.TITLE.upper(), PrefsniffAbout.VERSION))
    if monitor_dir_events:
        PrefsWatcher(plistpath)
    else:
        while True:
            try:
                diffs = PrefSniff(plistpath)
            except KeyboardInterrupt:
                print("Exiting.")
                exit(0)
            if show_diffs:
                print('\n'.join(diffs.diff))
            print(STARS)
            print("")
            for cmd in diffs.commands:
                print(cmd)
            print("")
            print(STARS)


if __name__ == '__main__':
    main(sys.argv[1:])
