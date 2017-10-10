#!/usr/bin/env python
import sys
import subprocess
import tempfile
import difflib
import plistlib
import os

class PrefSleuth(object):

    PLIST_TYPES={bool:"-bool",
                    int:"-int",
                    float:"-float",
                    str:"-string",
                    dict:"-dict",
                    list:"-array"}
    """
    Types for defaults we still need to handle
    data (hex-encoded binary data)
    date
    array-add
    dict-add
    """

    def __init__(self,plistpath):
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
        same = set(o for o in intersect_keys if d1[o] == d2[o])
        return added, removed, modified, same

    def _unified_diff(self,fromfile,tofile):
        fromlines=open(fromfile,"rb").readlines()
        tolines=open(tofile,"rb").readlines()
        return difflib.unified_diff(fromlines,tolines,fromfile,tofile)

    def _wait_for_prefchange(self):
        while True:
            line=sys.stdin.readline()
            """
            Parse opensnoop output:
              501    271 cfprefsd       5 /Users/zach/Library/Preferences/com.apple.Safari.plist
            """
            parts=line.split(None,5)
            if not len(parts)==5:
                continue
            if parts[3]=="-1":
                continue
            if parts[4]==self.plistpath:
                break

    def _generate_commands(self):
        commands=[]
        #defaults write com.apple.dock orientation -string 'left'
        defaults_write_fmt="defaults write %s %s %s '%s'"
        defaults_delete_fmt="defaults delete %s %s"
        domain=os.path.basename(self.plistpath).strip(".plist")
        for k,v in self.added:
            plist_type=self.PLIST_TYPES[type(v)]
            command=defaults_write_fmt % (domain,k,plist_type,v)
            commands.append(command)
        print self.modified
        for k,v in self.modified.items():
            #value is a tuple of (new,old)
            val=v[1]
            plist_type=self.PLIST_TYPES[type(val)]
            command=defaults_write_fmt % (domain,k,plist_type,val)
            commands.append(command)
        return commands


    def execute(self,args,stdout=None):
        subprocess.check_call(args,stdout=stdout)


def main(plistpath):
    while True:
        diffs=PrefSleuth(plistpath)
        print diffs.diff
        for cmd in diffs.commands:
            print cmd

if __name__ == '__main__':
    plistpath=sys.argv[1]
    main(plistpath)
