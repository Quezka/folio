"""Stand-ins for the network and the system installer."""


class FakeReleases:
    """A release feed that never touches the network."""

    def __init__(self, release=None):
        self.release = release
        self.downloads = []

    def latest(self):
        return self.release

    def download(self, asset, progress):
        progress(asset.size // 2, asset.size)
        progress(asset.size, asset.size)
        self.downloads.append(asset.name)
        return f"/tmp/{asset.name}"


class FakeInstaller:
    def __init__(self, supported=True, takes_over=False):
        self._supported = supported
        self.takes_over = takes_over
        self.installed = []

    def supported(self):
        return self._supported

    def pick(self, assets):
        return next((a for a in assets if a.name.endswith(".deb")), None)

    def install(self, path):
        self.installed.append(path)
        return self.takes_over


class FakeAccess:
    """Stands in for the Access helper: hands back whatever database a test gives it and
    remembers what it was asked to write."""

    def __init__(self, database=None):
        from folio.application.ports import AccessDatabase
        self.database = database or AccessDatabase(())
        self.read_paths = []
        self.written = []

    def read(self, path):
        self.read_paths.append(path)
        return self.database

    def write(self, path, database):
        self.written.append((path, database))
