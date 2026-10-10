from normalize import normalize
from storage import store

def process(value):
    return store(normalize(value))

