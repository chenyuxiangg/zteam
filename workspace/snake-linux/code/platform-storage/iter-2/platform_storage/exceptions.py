"""platform_storage.exceptions — 自定义异常基类。"""


class StorageError(Exception):
    """平台存储模块异常基类（用户数据目录 / IO / 权限错误）。

    携带原始异常链（raise X from e），便于上游 game-app 走 NFR-03
    "可读错误提示"路径。
    """