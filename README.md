Prefsniff
=========

*Author:* Zachary Cutlip, uid000 at gmail

`prefsniff` is a utility to watch macOS plist files for changes, and then autogenerate the `defaults` command to apply those changes. Its intended use is to have `prefsniff` watch a plist file while setting a system or application preference. The resulting defaults command can then be added to a shell script or incorporated into a configuration management system such as Ansible.

Installing
----------
    $ git clone <repo url> prefsniff
    $ cd prefsniff
    $ pip install -r ./requirements.txt


Using
-----
`prefsniff` has two modes of operation; directory mode and file mode.

- Directory mode: watch a directory (non-recursively) for plist files that are unlinked and replaced in order to observe what file backs a particular configuration setting.
- File mode: watch a plist file in order to represent its changes as one or more `defaults` command.

Directory mode example:

    $ ./prefsniff ~/Library/Preferences/
    Watching prefs file:
    Detected change: [created] /Users/zach/Library/Preferences/com.apple.dock.plist.DnakVR2
    Detected change: [modified] /Users/zach/Library/Preferences/
    Detected change: [deleted] /Users/zach/Library/Preferences/com.apple.dock.plist
    Detected change: [modified] /Users/zach/Library/Preferences/com.apple.dock.plist.DnakVR2
    Detected change: [moved] /Users/zach/Library/Preferences/com.apple.dock.plist.DnakVR2
    Detected change: [modified] /Users/zach/Library/Preferences/

File mode example:

    $ ./prefsniff ~/Library/Preferences/com.apple.dock.plist
    Watching prefs file: com.apple.dock.plist
    *****************************

    defaults write com.apple.dock orientation -string left

    *****************************
    Watching prefs file: com.apple.dock.plist

TODO
----

- Test for python 3 compat
- Implement `data` and `date` plist types
- Make an actual installer
- Clean up output so that it can be redirected to a shell script or similar
- Add additional output options (such as the name of a shell script to create)
- Split utility & API
    - Make prefsniff into a python module that exports API
    - Make a separate `prefsniff` command-line utility that uses the API

