class PSniffException(Exception):
    pass


class PSChangeTypeException(PSniffException):
    pass


class PSChangeTypeNotImplementedException(PSChangeTypeException):
    pass
