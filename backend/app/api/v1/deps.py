"""FastAPI 依赖注入提供者。

所有路由通过 `Depends(get_X)` 获取所需依赖。
容器在应用 lifespan 中构建一次，并保存在 `app.state` 上。
"""

from fastapi import Request


def get_container(request: Request):
    """返回挂载在 app state 上的 DI 容器。"""
    return request.app.state.container
