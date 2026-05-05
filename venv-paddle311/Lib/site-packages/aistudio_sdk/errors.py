"""
ERRORS
"""
class InvalidParameter(Exception):
    """error"""
    pass


class NotExistError(Exception):
    """error"""
    pass


class FileIntegrityError(Exception):
    """error"""
    pass


class RequestError(Exception):
    """error"""
    pass


def raise_on_error(rsp):
    """If response error, raise exception

    Args:
        rsp (_type_): The server response

    Raises:
        RequestError: the response error message.

    Returns:
        bool: True if request is OK, otherwise raise `RequestError` exception.
    """
    if rsp['total_count'] is not None:
        return True
    else:
        raise RequestError(rsp['Message'])