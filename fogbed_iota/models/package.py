import time
from typing import List, Optional

class MovePackage:
    """
    Represents a published Move package on IOTA blockchain.
    """

    def __init__(
        self,
        package_id: str,
        name: str,
        modules: List[str],
        digest: str,
        publisher: str,
        upgrade_cap_id: Optional[str] = None,
        version: int = 1,
    ):
        self.package_id = package_id
        self.name = name
        self.modules = modules
        self.digest = digest
        self.publisher = publisher
        self.upgrade_cap_id = upgrade_cap_id
        self.version = version
        self.deployed_at = time.time()

    def __repr__(self) -> str:
        upgradeable = f", upgradeable={bool(self.upgrade_cap_id)}" if self.upgrade_cap_id else ""
        return f"MovePackage(name='{self.name}', id='{self.package_id[:16]}...', v{self.version}{upgradeable})"

    def is_upgradeable(self) -> bool:
        return self.upgrade_cap_id is not None
