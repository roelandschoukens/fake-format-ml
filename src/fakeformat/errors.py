class ParseException(Exception):
    """Base class for parsing exceptions"""
    def __init__(self, message):
        self.message = message
