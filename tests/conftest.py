"""Point the app at a throwaway DB before it is imported anywhere."""
import os
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ankorov-test-"))
