from . import __summary__, __title__, __version__


class PrefsniffAbout(object):
    VERSION = __version__
    TITLE = __title__
    SUMMARY = __summary__

    def __str__(self):
        return "%s: %s version %s" % (self.TITLE, self.SUMMARY, self.VERSION)
