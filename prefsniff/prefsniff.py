#!/usr/bin/env python

import argparse
import datetime
import difflib
import os
import plistlib
import re
import subprocess
import sys
from pwd import getpwuid
from queue import Empty as QueueEmpty
from queue import Queue
from typing import List

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .changetypes import (
    PSChangeTypeArray,
    PSChangeTypeArrayAdd,
    PSChangeTypeBase,
    PSChangeTypeBool,
    PSChangeTypeData,
    PSChangeTypeDate,
    PSChangeTypeDict,
    PSChangeTypeDictAdd,
    PSChangeTypeFactory,
    PSChangeTypeFloat,
    PSChangeTypeInt,
    PSChangeTypeKeyDeleted,
    PSChangeTypeString
)
from .exceptions import PSChangeTypeNotImplementedException
from .version import PrefsniffAbout

STARS = "*****************************"


def parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "watchpath", help="Directory or plist file to watch for changes.")
    parser.add_argument(
        "--version",
        help="Show version and exit.",
        action='version',
        version=str(PrefsniffAbout()))
    parser.add_argument(
        "--show-diffs", help="Show diff of changed plist files.", action="store_true")
    parser.add_argument("--plist2",
                        help="Optionally compare WATCHPATH against this plist rather than waiting for changes to the original."
                        )
    args = parser.parse_args(argv)
    return args


class PrefSniff:
    STANDARD_PATHS = ["~/Library/Preferences",
                      "/Library/Preferences"]

    CHANGE_TYPES = {int: PSChangeTypeInt,
                    float: PSChangeTypeFloat,
                    str: PSChangeTypeString,
                    bool: PSChangeTypeBool,
                    dict: PSChangeTypeDict,
                    list: PSChangeTypeArray,
                    bytes: PSChangeTypeData,
                    datetime.datetime: PSChangeTypeDate}

    @classmethod
    def is_nsglobaldomain(cls, plistpath):
        nsglobaldomain = False
        base = os.path.basename(plistpath)
        if base.startswith(".GlobalPreferences"):
            nsglobaldomain = True

        return nsglobaldomain

    @classmethod
    def is_byhost(cls, plistpath):
        byhost = False
        dirname = os.path.dirname(plistpath)
        immediate_parent = os.path.basename(dirname)
        if "ByHost" == immediate_parent:
            byhost = True

        return byhost

    @classmethod
    def is_root_owned(cls, plistpath):
        return getpwuid(os.stat(plistpath).st_uid).pw_name == 'root'

    @classmethod
    def standard_path(cls, plistpath: str):
        standard = False
        path: str
        for path in cls.STANDARD_PATHS:
            path_real = os.path.expanduser(path)
            if plistpath.startswith(path):
                standard = True
                break
            elif plistpath.startswith(path_real):
                standard = True
                break

        return standard

    @classmethod
    def getdomain(cls, plistpath, byhost=False):
        domain = None

        globaldomain = cls.is_nsglobaldomain(plistpath)
        root_owned = cls.is_root_owned(plistpath)
        standard_path = cls.standard_path(plistpath)
        real_path = os.path.realpath(plistpath)
        # if root owned (like in /Library/Preferences), need to specify fully qualified
        # literal filename rather than a namespace
        if root_owned:
            domain = real_path
        elif not standard_path:
            domain = real_path
        elif globaldomain:
            domain = "NSGlobalDomain"
        elif byhost:
            # e.g.,
            # '~/Library/Preferences/ByHost/com.apple.windowserver.000E4DFD-62C8-5DC5-A2A4-42AFE04AAB87.plist
            # get just the filename
            base = os.path.basename(plistpath)
            # strip off .plist
            base = os.path.splitext(base)[0]
            # strip off UUID, leaving e.g., com.apple.windowserver
            domain = os.path.splitext(base)[0]
        else:
            base = os.path.basename(plistpath)
            domain = os.path.splitext(base)[0]

        return domain

    def __init__(self, plistpath, plistpath2=None):
        self.plist_dir = os.path.dirname(plistpath)
        self.plist_base = os.path.basename(plistpath)
        self.byhost = self.is_byhost(plistpath)
        self.pref_domain = self.getdomain(plistpath, byhost=self.byhost)

        self.plistpath = plistpath

        # Read the preference file before it changed
        with open(plistpath, 'rb') as f:
            pref1 = plistlib.load(f)

        if plistpath2 is None:
            self.plistpath2 = plistpath
            self._wait_for_prefchange()
        else:
            self.plistpath2 = plistpath2

        # Read the preference file after it changed
        with open(self.plistpath2, 'rb') as f:
            pref2 = plistlib.load(f)

        added, removed, modified, same = self._dict_compare(pref1, pref2)
        self.removed = {}
        self.added = {}
        self.modified = {}

        # At this stage, added and removed would be
        # a key:value added or removed from the top-level
        # <dict> of the plist
        if len(added):
            self.added = added
        if len(removed):
            self.removed = removed
        if len(modified):
            self.modified = modified

        self.changes = self._generate_changes()
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

    def _list_compare(self, list1, list2):
        list_diffs = {"same": False, "append_to_l1": None,
                      "subtract_from_l1": None}
        if list1 == list2:
            list_diffs["same"] = True
            return list_diffs
        if len(list2) > len(list1):
            if list1 == list2[:len(list1)]:
                list_diffs["append_to_l1"] = list2[len(list1):]

            return list_diffs
        elif len(list1) > len(list2):
            if list2 == list1[:len(list2)]:
                list_diffs["subtract_from_l1"] = list1[len(list2):]

            return list_diffs

        return list_diffs

    def _unified_diff(self, frompref, topref, path):
        # Convert both preferences to XML format
        fromxml = plistlib.dumps(
            frompref, fmt=plistlib.FMT_XML).decode('utf-8')
        toxml = plistlib.dumps(
            topref, fmt=plistlib.FMT_XML).decode('utf-8')

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

    def _generate_changes(self) -> List[PSChangeTypeArray]:
        change: PSChangeTypeBase = None
        changes = []
        # sub-dictionaries that must be rewritten because
        # something was removed.
        rewrite_dictionaries = {}

        # we can only append to existing arrays
        # if an array changes in any other way, we have to rewrite it
        rewrite_lists = {}
        domain = self.pref_domain
        for k, v in self.added.items():
            # pprint(v)
            change_type = self._change_type_lookup(v.__class__)
            if not change_type:
                print(v.__class__)
            try:
                change = change_type(domain, self.byhost, k, v)
            except PSChangeTypeNotImplementedException as e:
                change = ("key: %s, %s" % (k, str(e)))

            changes.append(change)

        for k in self.removed:
            change = PSChangeTypeKeyDeleted(domain, self.byhost, k)
            changes.append(change)

        for key, val in self.modified.items():
            if isinstance(val[1], dict):
                added, removed, modified, same = self._dict_compare(
                    val[0], val[1])
                if len(removed):
                    # There is no -dict-delete so we have to
                    # rewrite this sub-dictionary
                    rewrite_dictionaries[key] = val[1]
                    continue
                for subkey, subval in added.items():
                    change = PSChangeTypeDictAdd(
                        domain, self.byhost, key, subkey, subval)
                    changes.append(change)
                for subkey, subval_tuple in modified.items():
                    change = PSChangeTypeDictAdd(
                        domain, self.byhost, key, subkey, subval_tuple[1])
                    changes.append(change)
            elif isinstance(val[1], list):
                list_diffs = self._list_compare(val[0], val[1])
                if list_diffs["same"]:
                    continue
                elif list_diffs["append_to_l1"]:
                    append = list_diffs["append_to_l1"]
                    change = PSChangeTypeArrayAdd(domain, key, append)
                    changes.append(change)
                else:
                    rewrite_lists[key] = val[1]
            else:
                # for modified keys that aren't dictionaries, we treat them
                # like adds
                change_type = self._change_type_lookup(val[1].__class__)
                try:
                    change = change_type(domain, self.byhost, key, val[1])
                except PSChangeTypeNotImplementedException as e:
                    change = ("key: %s, %s" % (key, str(e)))
                changes.append(change)

        for key, val in rewrite_dictionaries.items():
            change = PSChangeTypeDict(domain, self.byhost, key, val)
            changes.append(change)

        for key, val in rewrite_lists.items():
            change = PSChangeTypeArray(domain, self.byhost, key, val)
            changes.append(change)

        return changes

    @property
    def commands(self):
        _commands = [ch.shell_command() for ch in self.changes]
        return _commands

    def execute(self, args, stdout=None):
        subprocess.check_call(args, stdout=stdout)


class PrefsWatcher:
    class _PrefsWatchFilter:

        def __init__(self, pattern_string, pattern_is_regex=False, negative_match=False):
            self.pattern = pattern_string
            self.regex = None
            if pattern_is_regex:
                self.regex = re.compile(pattern_string)
            self.negative_match = negative_match

        def passes_filter(self, input_string):
            match = False
            passes = False
            if not self.regex:
                match = self.pattern_string in input_string
            else:
                re_match = self.regex.match(input_string)
                if re_match is not None:
                    match = True

            if self.negative_match:
                passes = (not match)
            else:
                passes = match

            return passes

    def __init__(self, prefsdir):
        self.prefsdir = prefsdir
        self.filters = [self._PrefsWatchFilter(
            r".*\.plist$", pattern_is_regex=True)]
        self._watch_prefsdir()

    def _watch_prefsdir(self):
        event_queue = Queue()
        event_handler = PrefChangedEventHandler(None, event_queue)
        observer = Observer()
        observer.schedule(event_handler, self.prefsdir, recursive=False)
        observer.start()

        while True:
            try:
                changed = event_queue.get(True, 0.5)
                src_path = changed[1].src_path
                passes = True
                for _filter in self.filters:
                    if not _filter.passes_filter(src_path):
                        passes = False
                        break
                if not passes:
                    continue
                print("Detected change: [%s] %s" %
                      (changed[0], changed[1].src_path))
            except QueueEmpty:
                pass
            except KeyboardInterrupt:
                break
        observer.stop()
        observer.join()


class PrefChangedEventHandler(FileSystemEventHandler):

    def __init__(self, file_base_name, event_queue):
        super(self.__class__, self).__init__()
        if file_base_name is None:
            file_base_name = ""
        self.file_base_name = file_base_name
        self.event_queue = event_queue

    def on_created(self, event):
        if self.file_base_name not in os.path.basename(event.src_path):
            return
        self.event_queue.put(("created", event))

    def on_deleted(self, event):
        if self.file_base_name not in os.path.basename(event.src_path):
            return
        self.event_queue.put(("deleted", event))

    def on_modified(self, event):
        if self.file_base_name not in os.path.basename(event.src_path):
            return
        self.event_queue.put(("modified", event))

    def on_moved(self, event):
        if self.file_base_name not in os.path.basename(event.src_path):
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


def main():
    args = parse_args(sys.argv[1:])
    monitor_dir_events = False
    show_diffs = False

    plistpath = args.watchpath
    if os.path.isdir(plistpath):
        monitor_dir_events = True
    elif not os.path.isfile(plistpath):
        print("Error: %s is not a directory or file, or does not exist." % plistpath)
        exit(1)

    if args.show_diffs:
        show_diffs = True
    print("{} version {}".format(
        PrefsniffAbout.TITLE.upper(), PrefsniffAbout.VERSION))
    if monitor_dir_events:
        print("Watching directory: {}".format(plistpath))
        PrefsWatcher(plistpath)
    else:
        print("Watching prefs file: %s" % plistpath)
        done = False
        while not done:
            plist2 = None
            if args.plist2:
                plist2 = args.plist2
                done = True

            try:
                diffs = PrefSniff(plistpath, plistpath2=plist2)
            except KeyboardInterrupt:
                print("Exiting.")
                exit(0)

            print(STARS)
            print("")
            for ch in diffs.changes:
                ch_dict = dict(ch)
                new_ch = PSChangeTypeFactory.ps_change_type_from_dict(ch_dict)
                print(new_ch.shell_command())
                print("")
            if show_diffs:
                print('\n'.join(diffs.diff))
            print(STARS)


if __name__ == '__main__':
    main()
