"""zxgk 自定义异常"""


class WafBlockedError(Exception):
    """WAF 封禁：子站页面无 #yzm 表单元素"""


class CaptchaUnavailableError(Exception):
    """captcha-solver 服务不可用"""


class SubsiteNavError(Exception):
    """子站链接定位失败（CSS selector 失效）"""
