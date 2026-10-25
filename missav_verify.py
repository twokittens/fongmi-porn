# -*- coding: utf-8 -*-
from base.spider import Spider as BaseSpider

HOST = "https://missav.ai/"


class Spider(BaseSpider):

    def init(self, extend=""):
        pass

    def getName(self):
        return "MissAV 人机验证"

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

    def categoryContent(self, tid, pg, filter, extend):
        cookie = ""
        error = ""

        try:
            cookie = self.net.getCookie(HOST) or ""
        except Exception as e:
            error = str(e)

        has_clearance = "cf_clearance=" in cookie

        if has_clearance:
            status = "已检测到 cf_clearance"
        else:
            status = "未检测到 cf_clearance"

        items = [
            {
                "vod_id": "verify",
                "vod_name": "打开 MissAV 人机验证",
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

        if error:
            items.append({
                "vod_id": "error",
                "vod_name": "Cookie 接口异常",
                "vod_remarks": error[:80],
                "action": "check"
            })

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
                cookie = self.net.getCookie(HOST) or ""

                if "cf_clearance=" in cookie:
                    msg = "已检测到 cf_clearance"
                else:
                    msg = "未检测到 cf_clearance"

                return {"msg": msg}

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

