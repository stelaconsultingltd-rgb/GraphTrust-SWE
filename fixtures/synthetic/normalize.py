from validate import validate

def normalize(value):
    validate(value)
    return value.strip()

