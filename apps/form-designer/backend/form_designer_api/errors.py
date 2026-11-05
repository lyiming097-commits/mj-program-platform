class HTTPException(Exception):
    def __init__(self, status_code=400, detail="请求失败", headers=None):
        self.status_code = status_code
        self.detail = detail
        self.headers = headers or {}
        super().__init__(str(detail))
