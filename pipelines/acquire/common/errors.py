"""Acquisition failures. Each one stops the batch; none of them yields substitute data."""


class AcquisitionError(Exception):
    """Base class for a failed acquisition."""


class SourceUnavailable(AcquisitionError):
    """The upstream endpoint could not be reached after retries."""


class ChecksumMismatch(AcquisitionError):
    """Stored bytes do not match the expected digest."""


class InsufficientDisk(AcquisitionError):
    """The download would leave less free space than the configured floor."""


class MalformedSource(AcquisitionError):
    """A source file could not be parsed, including truncated archives."""


class SchemaDrift(AcquisitionError):
    """A source no longer has the fields its data contract requires."""


class CountMismatch(AcquisitionError):
    """The number of records received differs from what the source reported."""


class SelectionOutOfBounds(AcquisitionError):
    """The configured selection no longer falls inside the target size."""
