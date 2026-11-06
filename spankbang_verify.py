# -*- coding: utf-8 -*-
from base.spider import Spider as BaseSpider

HOST = "https://zh.spankbang.com/"


class Spider(BaseSpider):

    def init(self, extend=""):
        pass

    def getName(self):
        return "SpankBang 人机验证"

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def homeContent(self, filter):
        return {
            "class": [
                {
                    "type_id": "verify",
                    "type_name": "验证与诊断"
                }
            ]
        }

    def homeVideoContent(self):
        return {"list": []}

    def _cookie(self):
        try:
            return self.net.getCookie(HOST) or ""
        except Exception:
            return ""

    def categoryContent(self, tid, pg, filter, extend):
        cookie = self._cookie()
        status = "已检测到 cf_clearance" if "cf_clearance=" in cookie else "未检测到 cf_clearance"

        items = [
            {
                "vod_id": "verify",
                "vod_name": "打开 SpankBang 人机验证",
                "vod_remarks": "点击打开 WebView",
                "action": "verify"
            },
            {
                "vod_id": "check",
                "vod_name": "检查 Cookie 状态",
                "vod_remarks": status,
                "action": "check"
            }
        ]

        return {
            "list": items,
            "page": 1,
            "pagecount": 1,
            "limit": len(items),
            "total": len(items)
        }

    def action(self, action, value=""):
        if action == "verify":
            return {
                "web": {
                    "url": HOST,
                    "mode": "browser",
                    "cookie": [
                        {
                            "keys": ["cf_clearance"]
                        }
                    ]
                }
            }

        if action == "check":
            try:
                cookie = self._cookie()
                if "cf_clearance=" in cookie:
                    return {"msg": "已检测到 cf_clearance"}
                return {"msg": "未检测到 cf_clearance"}
            except Exception as e:
                return {"msg": "读取失败：" + str(e)}

        return {"msg": "未知操作"}

    def searchContent(self, key, quick, pg="1"):
        return {"list": []}

    def detailContent(self, ids):
        return {"list": []}

    def playerContent(self, flag, id, vipFlags):
        return {"parse": 0, "url": ""}

    def destroy(self):
        pass
