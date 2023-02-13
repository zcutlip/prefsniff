import inspect
import plistlib
import xml.etree.ElementTree as ET
from abc import ABCMeta
from shlex import quote as cmd_quote
from typing import Dict

from py_dict_repr.py_dict_repr import DictRepr

from .exceptions import (
    PSChangeTypeException,
    PSChangeTypeNotImplementedException
)


class PSChangeTypeRegistry(type):
    REGISTERED_CHANGE_TYPES = {}

    def __new__(cls, clsname, bases, dct, *args, **kwargs):
        newclass = super(PSChangeTypeRegistry, cls).__new__(
            cls, clsname, bases, dct
        )
        if newclass.CHANGE_TYPE:
            ch_type = newclass.CHANGE_TYPE
            if ch_type in cls.REGISTERED_CHANGE_TYPES:
                raise Exception(
                    "class {:s} attempting to register previously registered preference change type: {}".format(
                        cls.__name__, ch_type))
            cls.REGISTERED_CHANGE_TYPES[ch_type] = newclass
        return newclass

    @classmethod
    def ch_type_class_lookup(cls, ch_type: str):
        ch_type_class = cls.REGISTERED_CHANGE_TYPES[ch_type]
        return ch_type_class


PSChangeTypeMeta = type(
    'SBHeaderMeta', (ABCMeta, PSChangeTypeRegistry), {})


class PSChangeTypeFactory:

    @classmethod
    def ps_change_type_from_dict(cls, ch_type_dict: Dict):
        ch_type = ch_type_dict["change_type"]
        ch_type_class = PSChangeTypeRegistry.ch_type_class_lookup(ch_type)
        obj = ch_type_class.from_dict(ch_type_dict)
        return obj


class PSChangeTypeBase(DictRepr, metaclass=PSChangeTypeMeta):
    CHANGE_TYPE = None
    COMMAND = "defaults"
    ACTION = None
    TYPE = None

    def __init__(self, domain, byhost, key, value):
        if self.ACTION is None:
            raise NotImplementedError(
                "Need to sublclass and override cls.ACTION")
        self.command = self.COMMAND
        self.action = self.ACTION
        self.domain = domain
        self.key = key
        self.type = self.TYPE
        self.value = value
        self.converted_value = value
        self.byhost = byhost

    def keys(self):
        _keys = ["change_type", "command", "action",
                 "domain", "key", "type", "value", "byhost"]
        return _keys

    @classmethod
    def from_dict(cls, ch_type_dict: Dict):
        domain = ch_type_dict["domain"]
        byhost = ch_type_dict["byhost"]
        key = ch_type_dict["key"]
        value = ch_type_dict["value"]
        obj = cls(domain, byhost, key, value)
        return obj

    @property
    def change_type(self):
        return self.CHANGE_TYPE

    def _quote(self, value, quote=True):
        if quote:
            value = cmd_quote(value)
        return value

    def argv(self, quote=True):
        argv = [self.command]
        if self.byhost:
            argv.append("-currentHost")
        argv.append(self._quote(self.action, quote=quote))
        argv.append(self._quote(self.domain, quote=quote))
        argv.append(self._quote(self.key, quote=quote))
        if self.type is not None:
            type_arg = f"-{self.type}"
            argv.append(self._quote(type_arg, quote=quote))
        value_argv = self._value_argv(quote=quote)

        if value_argv is not None:
            argv.extend(value_argv)

        return argv

    def _value_argv(self, quote=True):

        value_argv = None
        if self.converted_value is not None:
            if isinstance(self.converted_value, (list, tuple)):
                value_argv = [self._quote(v, quote=quote)
                              for v in self.converted_value]
            else:
                if isinstance(self.converted_value, str):
                    value_string = self.converted_value
                else:
                    value_string = str(self.converted_value)
                value_argv = [self._quote(value_string, quote=quote)]

        return value_argv

    def shell_command(self):
        argv = self.argv(quote=True)
        command = ' '.join(argv)
        return command


class PSChangeTypeString(PSChangeTypeBase):
    CHANGE_TYPE = "string"
    ACTION = "write"
    TYPE = "string"


class PSChangeTypeKeyDeleted(PSChangeTypeString):
    CHANGE_TYPE = "deleted"
    ACTION = "delete"
    TYPE = None

    def __init__(self, domain, byhost, key, *args):
        super().__init__(domain, byhost, key, None)


class PSChangeTypeFloat(PSChangeTypeString):
    CHANGE_TYPE = "float"
    TYPE = "float"

    def __init__(self, domain, byhost, key, value):
        self.type = "-float"

        if not isinstance(value, float):
            raise PSChangeTypeException(
                "Float required for -float prefs change.")

        super().__init__(domain, byhost, key, value)


class PSChangeTypeInt(PSChangeTypeString):
    CHANGE_TYPE = "int"
    TYPE = "int"

    def __init__(self, domain, byhost, key, value):

        if not isinstance(value, int):
            raise PSChangeTypeException(
                "Integer required for -int prefs change.")

        super().__init__(domain, byhost, key, value)


class PSChangeTypeBool(PSChangeTypeString):
    CHANGE_TYPE = "bool"
    TYPE = "bool"

    def __init__(self, domain, byhost, key, value):
        if not isinstance(value, bool):
            raise PSChangeTypeException(
                "Boolean required for -bool prefs change.")
        super().__init__(domain, byhost, key, value)


class PSChangeTypeCompositeBase(PSChangeTypeBase):
    CHANGE_TYPE = None
    TYPE = None

    def to_xmlfrag(self, value):

        # create plist-serialized form of changed objects
        plist_str = plistlib.dumps(value, fmt=plistlib.FMT_XML).decode('utf-8')

        # remove newlines and tabs from plist
        plist_str = "".join([line.strip() for line in plist_str.splitlines()])
        # parse the plist xml doc, so we can pull out the important parts.
        tree = ET.ElementTree(ET.fromstring(plist_str))
        # get elements inside <plist> </plist>
        children = list(tree.getroot())
        # there can only be one element inside <plist>
        if len(children) < 1:
            fn = inspect.getframeinfo(inspect.currentframe()).function
            raise PSChangeTypeException(
                "%s: Empty dictionary for key %s" % (fn, str(self.key)))
        if len(children) > 1:
            fn = inspect.getframeinfo(inspect.currentframe()).function
            raise PSChangeTypeException(
                "%s: Something went wrong for key %s. Can only support one dictionary for dict change." % (fn, self.dict_key))
        # extract changed objects out of the plist element
        # python 2 & 3 compat
        # https://stackoverflow.com/questions/15304229/convert-python-elementtree-to-string#15304351
        xmlfrag = ET.tostring(children[0]).decode()
        return xmlfrag


class PSChangeTypeArray(PSChangeTypeCompositeBase):
    CHANGE_TYPE = "array"
    ACTION = "write"
    TYPE = None

    def __init__(self, domain, byhost, key, value):
        if not isinstance(value, list):
            raise PSChangeTypeException(
                "PSChangeTypeArray requires a list value type.")
        super().__init__(domain, byhost, key, value)
        self.converted_value = self.to_xmlfrag(value)


class PSChangeTypeDict(PSChangeTypeCompositeBase):
    CHANGE_TYPE = "dict"
    ACTION = "write"
    # We have to omit the -dict type
    # And just let defaults interpet the xml dict string
    TYPE = None

    def __init__(self, domain, byhost, key, value):
        if not isinstance(value, dict):
            raise PSChangeTypeException(
                "Dict required for -dict prefs change.")
        super().__init__(domain, byhost, key, value)
        self.converted_value = self.to_xmlfrag(value)


class PSChangeTypeDictAdd(PSChangeTypeCompositeBase):
    CHANGE_TYPE = "dict-add"
    ACTION = "write"
    TYPE = "dict-add"

    def __init__(self, domain, byhost, key, subkey, value):
        super().__init__(domain, byhost, key, value)
        self.subkey = subkey
        self.converted_value = self._generate_value_string(subkey, value)

    def _generate_value_string(self, subkey, value):
        xmlfrag = self.to_xmlfrag(value)
        return (subkey, xmlfrag)

    def keys(self):
        _keys = super().keys()
        _keys.extend(["subkey"])
        return _keys

    @classmethod
    def from_dict(cls, ch_type_dict: Dict):
        domain = ch_type_dict["domain"]
        byhost = ch_type_dict["byhost"]
        key = ch_type_dict["key"]
        subkey = ch_type_dict["subkey"]
        value = ch_type_dict["value"]
        obj = cls(domain, byhost, key, subkey, value)
        return obj

    # def __str__(self):
    #     # hopefully generate something like:
    #     #"dict-key 'val-to-add-to-dict'"
    #     # so we can generate a command like
    #     # defaults write foo -dict-add dict-key 'value'
    #     xmlfrag = self.xmlfrag
    #     return " %s '%s'" % (self.dict_key, xmlfrag)


class PSChangeTypeArrayAdd(PSChangeTypeArray):
    CHANGE_TYPE = "array-add"
    TYPE = "array-add"

    def __init__(self, domain, key, byhost, value):
        super().__init__(domain, byhost, key, value)
        self.converted_value = self._generate_value_string(value)

    def _generate_value_string(self, value):
        values = []
        for v in value:
            values.append(self.to_xmlfrag(v))
        return values


class PSChangeTypeData(PSChangeTypeString):
    CHANGE_TYPE = "data"

    def __init__(self, domain, byhost, key, value):
        raise PSChangeTypeNotImplementedException(
            "%s not implemented" % self.__class__.__name__)


class PSChangeTypeDate(PSChangeTypeString):
    CHANGE_TYPE = "date"

    def __init__(self, domain, byhost, key, value):
        raise PSChangeTypeNotImplementedException(
            "%s not implemented" % self.__class__.__name__)
