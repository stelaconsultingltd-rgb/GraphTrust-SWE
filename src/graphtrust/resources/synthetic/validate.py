from errors import invalid

def validate(value):
    if not isinstance(value, str):
        return invalid(value)
    return True

