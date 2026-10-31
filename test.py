
# -*- coding: utf-8 -*-

class Spider:
    def getName(self):
        return "Huangguo Python Test"

    def init(self, extend=""):
        pass

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def homeContent(self, filter=False):
        return {
            "class": [
                {
                    "type_id": "test",
                    "type_name": "Python加载测试"
                }
            ]
        }

    def homeVideoContent(self):
        return {"list": []}

    def categoryContent(
        self, tid, pg, filter=False, extend=None
    ):
        return {
            "list": [
                {
                    "vod_id": "test001",
                    "vod_name": "Python爬虫运行成功",
                    "vod_pic": "",
                    "vod_remarks": "FongMi 5.8.5"
                }
            ],
            "page": 1,
            "pagecount": 1
        }

    def detailContent(self, ids):
        return {"list": []}

    def searchContent(self, key, quick=False, pg="1"):
        return {"list": []}

    def playerContent(self, flag, id, vipFlags=None):
        return {"parse": 0, "url": ""}

    def localProxy(self, param):
        return [404, "text/plain", "Not Found"]
