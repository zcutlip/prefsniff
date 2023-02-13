Prefsniff
=========

*Author:* Zachary Cutlip, uid000 at gmail

`prefsniff` is a utility to watch macOS plist files for changes, and then autogenerate the `defaults` command to apply those changes. Its intended use is to have `prefsniff` watch a plist file while setting a system or application preference. The resulting defaults command can then be added to a shell script or incorporated into a configuration management system such as Ansible.

Installing
----------
If you're here to simply use `prefsniff` and not to hack on it, there's no need to clone the git repo. You may simply install from PyPI via `pip`:

    $ pip3 install prefsniff

Using
-----
`prefsniff` has two modes of operation; directory mode and file mode.

- Directory mode: watch a directory (non-recursively) for plist files that are unlinked and replaced in order to observe what file backs a particular configuration setting.
- File mode: watch a plist file in order to represent its changes as one or more `defaults` command.

Directory mode example:

    $ prefsniff ~/Library/Preferences
    PREFSNIFF version 0.1.0b3
    Watching directory: /Users/zach/Library/Preferences
    Detected change: [deleted] /Users/zach/Library/Preferences/com.apple.dock.plist
    Detected change: [created] /Users/zach/Library/Preferences/com.apple.dock.plist

File mode example:

    $ prefsniff ~/Library/Preferences/com.apple.dock.plist
    PREFSNIFF version 0.1.0b3
    Watching prefs file: /Users/zach/Library/Preferences/com.apple.dock.plist
    *****************************

    defaults write com.apple.dock orientation -string right

    *****************************


Additional Reading
------------------

[Advanced `defaults(1)` Usage](https://shadowfile.inode.link/blog/2018/06/advanced-defaults1-usage/)

An introduction to plist files and the `defaults(1)` command. Includes detailed explanation of each plist type and how to manipulate them with `defaults`.

[Defaults Non-obvious Locations](https://shadowfile.inode.link/blog/2018/08/defaults-non-obvious-locations/)

An explanation of various defaults domains and where their corresponding plist files can be found on disk.


[Autogenerating `defaults(1)` Commands](https://shadowfile.inode.link/blog/2018/08/autogenerating-defaults1-commands/)

An introduction to this tool, `prefsniff`, and how to use it to autogenerate `defaults` commands.

TODO
----

- Implement `data` and `date` plist types
- Clean up output so that it can be redirected to a shell script or similar
- Add additional output options (such as the name of a shell script to create)
- Split utility & API
    - Make prefsniff into a python module that exports API
    - Make a separate `prefsniff` command-line utility that uses the API

