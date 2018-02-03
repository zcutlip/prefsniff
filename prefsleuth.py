#!/usr/bin/env python



import sys
import subprocess
import tempfile
import difflib
import plistlib
import os
from watchdog.events import *
from watchdog.observers import Observer
import time
import os.path
from Queue import Queue
from Queue import Empty as QueueEmpty
from pprint import pprint
import xml.etree.ElementTree as ET


"""
Pulling out <dict> from xml plist:
import xml.etree.ElementTree as ET
>>> ET.tostring(root)
'<plist version="1.0">\n<dict>\n\t<key>1</key>\n\t<string>a</string>\n\t<key>2</key>\n\t<string>b</string>\n</dict>\n</plist>'
>>> root.find("dict")
<Element 'dict' at 0x106295a90>
>>> ET.tostring(root.find("dict"))
'<dict>\n\t<key>1</key>\n\t<string>a</string>\n\t<key>2</key>\n\t<string>b</string>\n</dict>\n'
"""


"""
To create the following foo.bar preference under the key "mydict":
{
    mydict = {
        enabled=1;
    };
}
We can do any of the following:
- Don't specify the type at all, and use an xml represenation of the dictionary
defaults write foo.bar mydict "<dict><key>enabled</key><string>1</string></dict>"
- Specify the type as -dict, followed by the key you want to add to mydict:
defaults write foo.bar mydict -dict mysubdict "<dict><key>somekey</key><string>1</string></dict>"
defaults write foo.bar mydict -dict enabled "<integer>1</integer>"

This creates or replaces 'mydict'
- Specify -dict-add in order to add to create mydict or add to it if it already exists
defaults write foo.bar mydict -dict-add mysubdict "<dict><key>somekey</key><string>1</string></dict>"
defaults write foo.bar mydict -dict-add enabled "<integer>1</integer>"
"""

class PSChangeTypeString(object):

    def __init__(self,domain, key, value=None):
        self.action="write"
        self.domain=domain
        self.key=key
        self.type="-string"
        self.value=value

    def __str__(self):
        #defaults action domain key
        fmt="defaults %s %s %s"
        cmd=(fmt % (self.action,self.domain,self.key))
        #some commands work without a type and are easier that way
        if not self.type == None:
            cmd+=" %s" % self.type
        cmd+=" %s" % self.value
        return cmd

class PSChangeTypeInt(PSChangeTypeString):
    def __init__(self,domain,key,value):
        super(PSChangeTypeInt,self).__init__(domain,key)
        self.type="-int"
        if not isinstance(value,int):
            raise Exception("Integer required for -int prefs change.")
        self.value=str(value)

class PSChangeTypeBool(PSChangeTypeString):
    def __init__(self,domain,key,value):
        super(PSChangeTypeBool,self).__init__(domain,key)
        self.type="-bool"
        if not isinstance(value,bool):
            raise Exception("Boolean required for -bool prefs change.")
        self.value=str(value)

class PSChangeTypeDict(PSChangeTypeString):
    def __init__(self,domain,key,value):
        super(PSChangeTypeDict,self).__init__(domain,key)
        self.type=None
        #TODO: not sure what to do here. I want to sanity check we got handed a dict
        #unless we've been subclassed.
        self.value=value
        if isinstance(value,dict):
            self.value="\'%s\'" % self.to_xmlfrag(value)



    def to_xmlfrag(self,value):

        #create plist-serialized form of changed objects
        plist_str=plistlib.writePlistToString(value)
        #remove newlines and tabs from plist
        plist_str="".join([line.strip() for line in plist_str.splitlines()])
        #parse the plist xml doc, so we can pull out the important parts.
        tree=ET.ElementTree(ET.fromstring(plist_str))
        #get elements inside <plist> </plist>
        children=list(tree.getroot())
        #there can only be one element inside <plist>
        if len(children) < 1:
            raise Exception("Empty dictionary for key %s" % str(self.key))
        if len(children) > 1:
            raise Exception("Something went wrong for key %s. Can only support one dictionary for dict change." % self.dict_key)
        #extract changed objects out of the plist element
        xmlfrag=ET.tostring(children[0])
        return xmlfrag

class PSChangeTypeDictAdd(PSChangeTypeDict):

    def __init__(self,domain,key,subkey,value):
        super(PSChangeTypeDictAdd,self).__init__(domain,key,value)
        self.type="-dict-add"
        self.subkey=subkey
        self.value=self.__generate_value_string(subkey,value)
        print self.value

    def __generate_value_string(self,subkey,value):
        xmlfrag=self.to_xmlfrag(value)
        valuestring="%s \'%s\'" % (subkey,xmlfrag)
        return valuestring


class PrefSleuthDictAddList(list):
    def __init__(self,parent_key,modified_dict):
        super(PrefSleuthDictAddList,self).__init__()
        self.parent_key=parent_key
        for key,value in modified_dict.items():
            dict_add=PrefSleuthDictAdd(key,value[0],value[1])
            self.append(dict_add)


class PrefSleuthDict(object):
    def __init__(self,dict_key,old_val,new_val):
        self.dict_key=dict_key
        self.old_val=old_val
        self.new_val=new_val

    def __xml_frag(self):

        #create plist-serialized form of changed objects
        plist_str=plistlib.writePlistToString(self.new_val)
        #remove newlines and tabs from plist
        plist_str="".join([line.strip() for line in plist_str.splitlines()])
        #parse the plist xml doc, so we can pull out the important parts.
        tree=ET.ElementTree(ET.fromstring(plist_str))
        #get elements inside <plist> </plist>
        children=list(tree.getroot())
        #there can only be one element inside <plist>
        if len(children) < 1:
            raise Exception("No changed values found for key: %s" % str(self.dict_key))
        if len(children) > 1:
            raise Exception("Multiple changed values found for key: %s, can only support one dict-add change." % self.dict_key)
        #extract changed objects out of the plist element

        xmlfrag=ET.tostring(child[0])
        return xmlfrag



    def __str__(self):
        #hopefully generate something like:
        #"dict-key 'val-to-add-to-dict'"
        #so we can generate a command like
        #defaults write foo -dict-add dict-key 'value'
        xmlfrag=self.__xml_frag()
        return " %s '%s'" % (self.dict_key,self.xmlfrag)


class PrefSleuth(object):

    PLIST_TYPES={bool:"-bool",
                    int:"-int",
                    float:"-float",
                    str:"-string",
                    dict:"-dict",
                    list:"-array",
                    PrefSleuthDict:"-dict-add"}
    """
    Types for defaults we still need to handle
    data (hex-encoded binary data)
    date
    array-add
    dict-add
    """

    def __init__(self,plistpath):
        self.plist_dir=os.path.dirname(plistpath)
        self.plist_base=os.path.basename(plistpath)

        self.plistpath=plistpath
        print plistpath
        plist_to_xml=["plutil", "-convert", "xml1", "-o", "-","%s"%plistpath]
        tempfile1=tempfile.mkstemp()
        tempfile2=tempfile.mkstemp()
        self.execute(plist_to_xml,stdout=tempfile1[0])
        pref1=plistlib.readPlist(tempfile1[1])
        self._wait_for_prefchange()
        self.execute(plist_to_xml,stdout=tempfile2[0])
        pref2=plistlib.readPlist(tempfile2[1])
        added,removed,modified,same=self._dict_compare(pref1,pref2)
        self.removed={}
        self.added={}
        self.modified={}

        if len(added):
            self.added=added
        if len(removed):
            self.removed=removed
        if len(modified):
            for k,v in modified.items():
                if isinstance(v[0],dict):
                    print "Comparing modified sub-dictionaries."
                    a,r,m,s=self._dict_compare(v[0],v[1])
                    print "Modified sub-dictionary"
                    for k1,v1 in m.items():
                        print "key:%s" % k1
                        pprint(v1[1])

            self.modified=modified
        self.commands=self._generate_commands()
        self.diff=""
        for line in self._unified_diff(tempfile1[1],tempfile2[1]):
            self.diff+=line

    def _dict_compare(self,d1, d2):
        d1_keys = set(d1.keys())
        d2_keys = set(d2.keys())
        intersect_keys = d1_keys.intersection(d2_keys)
        added = d2_keys - d1_keys
        removed = d1_keys - d2_keys
        modified = {o : (d1[o], d2[o]) for o in intersect_keys if d1[o] != d2[o]}
        #pprint(modified)
        same = set(o for o in intersect_keys if d1[o] == d2[o])
        return added, removed, modified, same

    def _unified_diff(self,fromfile,tofile):
        fromlines=open(fromfile,"rb").readlines()
        tolines=open(tofile,"rb").readlines()
        return difflib.unified_diff(fromlines,tolines,fromfile,tofile)

    def _wait_for_prefchange(self):
        print("Waiting for pref change.")
        event_queue=Queue()
        event_handler=PrefChangedEventHandler(self.plist_base,event_queue)
        observer = Observer()
        observer.schedule(event_handler, self.plist_dir, recursive=False)
        observer.start()
        pref_updated=False
        try:
            while not pref_updated:
                #print("Pref not updated.")
                try:
                    #print("Getting event from event queue.")
                    event=event_queue.get(True,0.5)
                    print("%s" % event[0])
                    print("%s" % os.path.basename(event[1].src_path))
                    if event[0]=="moved"  and os.path.basename(event[1].dest_path)==self.plist_base:
                        print "%s moved to %s" % (event[1].src_path,event[1].dest_path)
                        pref_updated=True
                    if event[0]== "modified" and os.path.basename(event[1].src_path)==self.plist_base:
                        print "%s modified" % event[1].src_path
                        pref_updated=True
                    if event[0]=="created" and os.path.basename(event[1].src_path) == self.plist_base:
                        print "%s created" % event[1].src_path
                        pref_updated=True
                except QueueEmpty:
                    pass
        except KeyboardInterrupt:
            print "KeyboardInterrupt"
            observer.stop()
            raise
        observer.stop()
        observer.join()

    def _plist_type_lookup(self,obj):
        try:
            self.PLIST_TYPES[type(obj)]
        except KeyError:
            return self._plist_type_slow_search(obj)

    def _plist_type_slow_search(self,obj):
        print "Searching for match for class %s" % type(obj).__name__
        for cls in self.PLIST_TYPES.keys():
            if isinstance(obj,cls):
                return self.PLIST_TYPES[cls]
        raise Exception("Superclass not found for %s" %type(obj).__name__)

    def _generate_commands(self):
        commands=[]
        #defaults write com.apple.dock orientation -string 'left'
        defaults_write_fmt="defaults write %s %s %s '%s'"
        defaults_dict_add_fmt="defaults write %s %s -dict-add %s '%s'"
        defaults_delete_fmt="defaults delete %s %s"
        domain=os.path.basename(self.plistpath).strip(".plist")
        for k,v in self.added:
            try:
                plist_type=self._plist_type_lookup(val)
            except KeyError as ke:
                print k,v
                print "error for self.added"
                print ke
                break
            command=defaults_write_fmt % (domain,k,plist_type,v)
            commands.append(command)
        #print self.modified
        for k,v in self.modified.items():
            #value is a tuple of (new,old)
            val=v[0]
            print k
            print val
            try:
                plist_type=self._plist_type_lookup(val)
            except KeyError as ke:
                print k,val
                print "error for self.modified"
                print ke
                break
            command=defaults_write_fmt % (domain,k,plist_type,val)
            commands.append(command)
        return commands


    def execute(self,args,stdout=None):
        subprocess.check_call(args,stdout=stdout)

class PrefsWatcher(object):
    def __init__(self, prefsdir):
        self.prefsdir=prefsdir
        self._watch_prefsdir()

    def _watch_prefsdir(self):
        event_queue=Queue()
        event_handler=PrefChangedEventHandler(None,event_queue)
        observer = Observer()
        observer.schedule(event_handler, self.prefsdir, recursive=False)
        observer.start()
        while True:
            try:
                event_queue.get(True,0.5)
            except QueueEmpty:
                pass
            except KeyboardInterrupt:
                break
        observer.stop()
        observer.join()

class PrefChangedEventHandler(FileSystemEventHandler):

    def __init__(self,file_base_name,event_queue):
        super(self.__class__,self).__init__()
        if file_base_name==None:
            file_base_name=""
        self.file_base_name=file_base_name
        self.event_queue=event_queue
        print("Watching prefs file: %s" % self.file_base_name)


    def on_created(self,event):
        if not self.file_base_name in os.path.basename(event.src_path):
            return
        print("FileCreatedEvent")
        print event.src_path
        self.event_queue.put(("created",event))

    def on_deleted(self,event):
        if not self.file_base_name in os.path.basename(event.src_path):
            return
        print("FileDeletedEvent")
        print event.src_path
        self.event_queue.put(("deleted",event))

    def on_modified(self,event):
        if not self.file_base_name in os.path.basename(event.src_path):
            return
        print("FileModifiedEvent")
        print event.src_path
        self.event_queue.put(("modified",event))

    def on_moved(self,event):
        if not self.file_base_name in os.path.basename(event.src_path):
            return
        print("FileMovedEvent")
        print event.src_path
        self.event_queue.put(("moved",event))

def main(plistpath,monitor_dir_events):
    if monitor_dir_events:
        PrefsWatcher(plistpath)
    else:
        while True:
            diffs=PrefSleuth(plistpath)
            print diffs.diff
            for cmd in diffs.commands:
                print cmd

def test_dict_add(domain,key,subkey,value):
    prefchange=PSChangeTypeDictAdd(domain,key,subkey,value)
    print str(prefchange)

def test_dict_add_dict(args):
    domain=args[0]
    key=args[1]
    subkey=args[2]
    value={"mykey1":2.0,"mykey2":7}
    test_dict_add(domain,key,subkey,value)

def test_dict_add_float(args):
    domain=args[0]
    key=args[1]
    subkey=args[2]
    value=2.0
    test_dict_add(domain,key,subkey,value)
def test_write_dict(args):
    domain=args[0]
    key=args[1]
    value={"dictkey1":2.0,"dictkey2":{"subkey":'7'}}
    prefchange=PSChangeTypeDict(domain,key,value)
    print str(prefchange)

if __name__ == '__main__':
    if "test-dict-add-float" == sys.argv[1]:
        test_dict_add_float(sys.argv[2:])
        exit(0)

    if "test-dict-add-dict" == sys.argv[1]:
        test_dict_add_dict(sys.argv[2:])
        exit(0)

    if "test-write-dict" == sys.argv[1]:
        test_write_dict(sys.argv[2:])
        exit(0)

    plistpath=sys.argv[1]
    monitor_dir_events=False
    if(os.path.isdir(plistpath)):
        print("Watching events for directory: %s" % plistpath)
        monitor_dir_events=True
    main(plistpath,monitor_dir_events)
