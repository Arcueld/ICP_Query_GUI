import asyncio
import aiohttp
import cv2
import time
import hashlib
import re
import base64
import os
import numpy as np
import ujson
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from detnate import detnate
from aiohttp import TCPConnector
from mlog import logger
import warnings
warnings.filterwarnings("ignore", category=UserWarning)
import ssl
from contextlib import asynccontextmanager
import threading
from load_config import config
from cachetools import TTLCache
ssl._create_default_https_context = ssl._create_unverified_context()

class ProxyManager:
    """统一的代理管理器"""
    
    def __init__(self):
        self.proxy_config = getattr(config, 'proxy', object())
        self.static_proxy = None
        self._init_static_proxy()
    
    def _init_static_proxy(self):
        """初始化静态代理配置"""
        static_config = getattr(self.proxy_config, 'static_proxy', object())
        if getattr(static_config, 'enable', False):
            proxy_type = getattr(static_config, 'type', 'http')
            host = getattr(static_config, 'host', '')
            port = getattr(static_config, 'port', 0)
            username = getattr(static_config, 'username', '')
            password = getattr(static_config, 'password', '')
            
            # 只支持 HTTP/HTTPS 代理
            if proxy_type not in ['http', 'https']:
                logger.error(f"不支持的代理类型: {proxy_type}，只支持 http 和 https")
                return
            
            if host and port:
                if username and password:
                    self.static_proxy = f"{proxy_type}://{username}:{password}@{host}:{port}"
                else:
                    self.static_proxy = f"{proxy_type}://{host}:{port}"
                logger.info(f"静态代理已配置: {self.static_proxy}")
            else:
                logger.warning("代理配置不完整，请检查 host 和 port 配置")
    
    def get_proxy(self):
        """获取代理地址，按优先级返回"""
        # 1. 静态代理（最高优先级）
        if self.static_proxy:
            return self.static_proxy
        
        # 3. API代理池
        if getattr(getattr(self.proxy_config, 'extra_api', object()), 'enable', False):
            # 这里需要从代理池获取，暂时返回None
            return None
        
        return None

class beian:
    def __init__(self):
        self.typj = {
            0: ujson.dumps(
                {"pageNum": "", "pageSize": "", "unitName": "", "serviceType": 1}
            ),  # 网站
            1: ujson.dumps(
                {"pageNum": "", "pageSize": "", "unitName": "", "serviceType": 6}
            ),  # APP
            2: ujson.dumps(
                {"pageNum": "", "pageSize": "", "unitName": "", "serviceType": 7}
            ),  # 小程序
            3: ujson.dumps(
                {"pageNum": "", "pageSize": "", "unitName": "", "serviceType": 8}
            ),  # 快应用
        }
        self.btypj = {
            0: ujson.dumps({"domainName": ""}),
            1: ujson.dumps({"serviceName": "", "serviceType": 6}),
            2: ujson.dumps({"serviceName": "", "serviceType": 7}),
            3: ujson.dumps({"serviceName": "", "serviceType": 8}),
        }
        self.cookie_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.41 Safari/537.36 Edg/101.0.1210.32"
        }
        self.home = "https://beian.miit.gov.cn/"
        self.url = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/auth"
        self.getCheckImage = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/image/getCheckImagePoint"
        self.checkImage = (
            "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/image/checkImage"
        )
        # 正常查询
        self.queryByCondition = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/icpAbbreviateInfo/queryByCondition"
        # 违法违规域名查询
        self.blackqueryByCondition = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/blackListDomain/queryByCondition"
        # 违法违规APP,小程序,快应用
        self.blackappAndMiniByCondition = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/blackListDomain/queryByCondition_appAndMini"
        # APP/小程序/快应用详情查询接口
        self.queryDetailByAppAndMiniId = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/icpAbbreviateInfo/queryDetailByAppAndMiniId"
        self.sign = "eyJ0eXBlIjozLCJleHREYXRhIjp7InZhZnljb2RlX2ltYWdlX2tleSI6IjUyZWI1ZTcyODViNzRmNWJhM2YwYzBkNTg0YTg3NmVmIn0sImUiOjE3NTY5NzAyNDg4MjN9.Ngpkwn4T7sQoQF9pCk_sQQpH61wQUEKnK2sQ8hDIq-Q"
        self.token = ""
        self.token_expire = 0
        self.det = detnate()
        self._loop = asyncio.new_event_loop()
        # 增加超时时间，特别是对于代理连接
        base_timeout = getattr(getattr(config, 'system', object()), 'http_client_timeout', 30)
        self.timeout = aiohttp.ClientTimeout(
            total=base_timeout * 2,  # 总超时时间翻倍
            connect=base_timeout,    # 连接超时
            sock_read=base_timeout,  # 读取超时
            sock_connect=base_timeout  # socket连接超时
        )
        
        # 连接池配置
        self.connector_config = {
            'limit': 100,
            'limit_per_host': 30,
            'ttl_dns_cache': 300,
            'use_dns_cache': True,
            'ssl': False,
            'keepalive_timeout': 60,
        }

        self._blocked_ip_cache = TTLCache(maxsize=1000, ttl=300)
        self._blocked_ip_lock = threading.Lock()
        
        # 初始化代理管理器
        self.proxy_manager = ProxyManager()
    
    def _ensure_loop(self):
        if not getattr(self, "_loop", None) or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
    
    def run_async(self, coro):
        """在内部事件循环中运行协程，避免频繁创建新循环"""
        self._ensure_loop()
        return self._loop.run_until_complete(coro)
    
    def _add_blocked_ip(self, ip):
        """将IP添加到黑名单缓存"""
        if not ip:
            return
        with self._blocked_ip_lock:
            self._blocked_ip_cache[ip] = True
            logger.info(f"IP {ip} 被创宇盾拦截已添加到黑名单缓存，5分钟后恢复使用")

    def _is_ip_blocked(self, ip):
        """检查IP是否在黑名单缓存中"""
        if not ip:
            return False
        with self._blocked_ip_lock:
            return ip in self._blocked_ip_cache
        

    async def _get_connector(self, proxy_url=None):
        """创建连接器，支持HTTP/HTTPS代理"""
        # 普通连接器（HTTP/HTTPS代理通过aiohttp的proxy参数处理）
        connector = TCPConnector(**self.connector_config)
        return connector

    @asynccontextmanager
    async def get_session(self, proxy=""):
        # 为每个session创建独立的连接器
        connector = await self._get_connector(proxy)
        
        session = aiohttp.ClientSession(
            timeout=self.timeout,
            connector=connector,
            headers={'Connection': 'keep-alive'}
        )
        
        try:
            yield session
        finally:
            # 确保session和connector都被正确关闭
            await session.close()
            await connector.close()

    async def get_token(self):
        import uuid
        base_header = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.41 Safari/537.36 Edg/101.0.1210.32",
            "Origin": "https://beian.miit.gov.cn",
            "Referer": "https://beian.miit.gov.cn/",
            "Cookie": f"__jsluid_s={uuid.uuid4().hex}",
            "Accept": "application/json, text/plain, */*",
        }
        
        if self.token_expire > int(time.time() * 1000):
            return True, self.token, base_header
        
        timeStamp = round(time.time() * 1000)
        authSecret = "testtest" + str(timeStamp)
        authKey = hashlib.md5(authSecret.encode(encoding="UTF-8")).hexdigest()
        auth_data = {"authKey": authKey, "timeStamp": timeStamp}
        
        try:
            proxy = self.proxy_manager.get_proxy()
            async with self.get_session(proxy) as session:
                current_ip = None
                if hasattr(session, '_connector') and hasattr(session._connector, '_local_addr'):
                    current_ip = session._connector._local_addr[0] if session._connector._local_addr else None
                async with session.post(self.url, data=auth_data, headers=base_header, proxy=proxy if proxy else None) as req:
                    req_text = await req.text()

            if "当前访问疑似黑客攻击" in req_text:
                if current_ip:
                    self._add_blocked_ip(current_ip)
                return False, "当前访问已被创宇盾拦截", ""
            
            t = ujson.loads(req_text)
            token = t["params"]["bussiness"]
            expire = int(time.time() * 1000) + t["params"]["expire"]
            
            self.token = token
            self.token_expire = expire
            
            return True, token, base_header
        except Exception as e:
            logger.error(f"get_token Faile : {e}")
            return False, str(e), ""

    async def get_cookie(self):
        proxy = self.proxy_manager.get_proxy()
        async with await self.get_session(proxy) as session:
            async with session.get(self.home, headers=self.cookie_headers, proxy=proxy if proxy else None) as req:
                res = await req.text()
                return re.compile("[0-9a-z]{32}").search(str(req.cookies))[0]

    # 进行aes加密
    def get_pointJson(self, value, key):
        cipher = AES.new(key.encode(), AES.MODE_ECB)
        ciphertext = cipher.encrypt(pad(ujson.dumps(value).encode(), AES.block_size))
        ciphertext_base64 = base64.b64encode(ciphertext)
        return ciphertext_base64.decode("utf-8")

    def get_clientUid(self):
        import random
        characters = "0123456789abcdef"
        unique_id = ["0"] * 36

        for i in range(36):
            unique_id[i] = random.choice(characters)

        unique_id[14] = "4"
        unique_id[19] = characters[(3 & int(unique_id[19], 16)) | 8]
        unique_id[8] = unique_id[13] = unique_id[18] = unique_id[23] = "-"

        point_id = "point-" + "".join(unique_id)

        return ujson.dumps({"clientUid": point_id})

    async def check_img(self, max_retries=None):
        """
        验证码识别，支持多次重试
        
        Args:
            max_retries: 最大重试次数 从配置文件读取
            
        Returns:
            tuple: (success, result, token, sign, base_header)
        """
        if max_retries is None:
            max_retries = getattr(getattr(config, 'captcha', object()), 'captcha_retry_times', 5)
        
        for attempt in range(max_retries):
            try:
                logger.info(f"验证码识别尝试 {attempt + 1}/{max_retries}")
                
                success, token, base_header = await self.get_token()
                if not success:
                    if attempt == max_retries - 1:
                        return False, token, '', '', ''
                    
                    # 检查是否启用了代理池，如果启用则等待指定时间再重试
                    proxy_config = getattr(config, 'proxy', object())
                    captcha_config = getattr(config, 'captcha', object())
                    extra_api_config = getattr(proxy_config, 'extra_api', object())
                    if (getattr(extra_api_config, 'enable', False) and getattr(extra_api_config, 'auto_maintenace', False)):
                        delay = getattr(captcha_config, 'proxy_retry_delay', 1)
                        logger.info(f"检测到代理池已启用，等待{delay}秒后重试...")
                        await asyncio.sleep(delay)
                    
                    continue
                
                data = self.get_clientUid()
                clientUid = ujson.loads(data)["clientUid"]
                length = str(len(str(data).encode("utf-8")))
                base_header.update({"Content-Length": length, "Token": token})
                base_header["Content-Type"] = "application/json"
                
                try:
                    proxy = self.proxy_manager.get_proxy()
                    async with self.get_session(proxy) as session:
                        async with session.post(self.getCheckImage, data=data, headers=base_header, proxy=proxy if proxy else None) as req:
                            res = await req.json()
                except Exception as e:
                    logger.warning(f"请求验证码时失败：{e}")
                    if attempt == max_retries - 1:
                        return False, f"请求验证码时失败：{e}", '', '', ''
                    
                    # 检查是否启用了代理池，如果启用则等待指定时间再重试
                    proxy_config = getattr(config, 'proxy', object())
                    captcha_config = getattr(config, 'captcha', object())
                    extra_api_config = getattr(proxy_config, 'extra_api', object())
                    if (getattr(extra_api_config, 'enable', False) and getattr(extra_api_config, 'auto_maintenace', False)):
                        delay = getattr(captcha_config, 'proxy_retry_delay', 1)
                        logger.info(f"检测到代理池已启用，等待{delay}秒后重试...")
                        await asyncio.sleep(delay)
                    
                    continue
            
                p_uuid = res["params"]["uuid"]
                big_image = res["params"]["bigImage"]
                small_image = res["params"]["smallImage"]
                secretKey = res["params"]["secretKey"]
                wordCount = res["params"]["wordCount"]
                
                start = time.time()
                success, selice_small = await self.small_selice(small_image, big_image)
                if not success:
                    logger.warning(f"验证码切割失败：{selice_small}")
                    if attempt == max_retries - 1:
                        return False, "selice_small", '', '', ''
                    
                    # 检查是否启用了代理池，如果启用则等待指定时间再重试
                    proxy_config = getattr(config, 'proxy', object())
                    captcha_config = getattr(config, 'captcha', object())
                    extra_api_config = getattr(proxy_config, 'extra_api', object())
                    if (getattr(extra_api_config, 'enable', False) and getattr(extra_api_config, 'auto_maintenace', False)):
                        delay = getattr(captcha_config, 'proxy_retry_delay', 1)
                        logger.info(f"检测到代理池已启用，等待{delay}秒后重试...")
                        await asyncio.sleep(delay)
                    
                    continue
                
                logger.info(f"预测用时 {time.time() - start} s")

                pointJson = self.get_pointJson(selice_small, secretKey)
                data = ujson.loads(
                    ujson.dumps(
                        {
                            "token": p_uuid,
                            "secretKey": secretKey,
                            "clientUid": clientUid,
                            "pointJson": pointJson,
                        }
                    )
                )
                length = str(len(str(data).encode("utf-8")))
                base_header.update({"Content-Length": length})
                
                proxy = self.proxy_manager.get_proxy()
                async with self.get_session(proxy) as session:
                    async with session.post(self.checkImage, json=data, headers=base_header, proxy=proxy if proxy else None) as req:
                        res = await req.text()
                
                data = ujson.loads(res)
                if data["success"] == False:
                    logger.warning(f"验证码识别失败，尝试 {attempt + 1}/{max_retries}")
                    
                    # 不保存失败的验证码图片（功能已禁用）
                    
                    if attempt == max_retries - 1:
                        return False, "验证码识别失败", '', '', ''
                    
                    # 检查是否启用了代理池，如果启用则等待指定时间再重试
                    proxy_config = getattr(config, 'proxy', object())
                    captcha_config = getattr(config, 'captcha', object())
                    extra_api_config = getattr(proxy_config, 'extra_api', object())
                    if (getattr(extra_api_config, 'enable', False) and getattr(extra_api_config, 'auto_maintenace', False)):
                        delay = getattr(captcha_config, 'proxy_retry_delay', 1)
                        logger.info(f"检测到代理池已启用，等待{delay}秒后重试...")
                        await asyncio.sleep(delay)
                    
                    continue
                else:
                    logger.info(f"验证码识别成功，尝试次数：{attempt + 1}")
                    return True, p_uuid, token, data["params"]["sign"], base_header
            
            except Exception as e:
                logger.error(f"验证码识别异常，尝试 {attempt + 1}/{max_retries}：{e}")
                if attempt == max_retries - 1:
                    return False, f"验证码识别异常：{e}", '', '', ''
                
                # 检查是否启用了代理池，如果启用则等待1秒再重试
                proxy_config = getattr(config, 'proxy', object())
                extra_api_config = getattr(proxy_config, 'extra_api', object())
                if (getattr(extra_api_config, 'enable', False) and getattr(extra_api_config, 'auto_maintenace', False)):
                    logger.info("检测到代理池已启用，等待1秒后重试...")
                    await asyncio.sleep(1)
                
                continue
        
        return False, "验证码识别失败，已达到最大重试次数", '', '', ''

    async def small_selice(self, small_image, big_image):
        isma = cv2.imdecode(
            np.frombuffer(base64.b64decode(small_image), np.uint8), cv2.COLOR_GRAY2RGB
        )

        isma = cv2.cvtColor(isma, cv2.COLOR_BGRA2BGR) 
        ibig = cv2.imdecode(
            np.frombuffer(base64.b64decode(big_image), np.uint8), cv2.COLOR_GRAY2RGB
        )

        captcha_config = getattr(config, 'captcha', object())
        if getattr(captcha_config, 'coding_code', 'auto') == 'labour':
            def mouse_callback(event, x, y, flags, param):
                if event == cv2.EVENT_LBUTTONDOWN:
                    data.append({"x":x,"y":y})
                    if len(data) == 4:
                        cv2.destroyAllWindows()
            data = []
            # 确保两个图像的通道数量一致
            if ibig.shape[2] != isma.shape[2]:
                if ibig.shape[2] == 1:
                    ibig = cv2.cvtColor(ibig, cv2.COLOR_GRAY2BGR)
                elif ibig.shape[2] == 4 and isma.shape[2] == 3:
                    isma = cv2.cvtColor(isma, cv2.COLOR_BGR2BGRA)
                elif ibig.shape[2] == 3 and isma.shape[2] == 4:
                    ibig = cv2.cvtColor(ibig, cv2.COLOR_BGR2BGRA)
                elif ibig.shape[2] == 3 and isma.shape[2] == 1:
                    isma = cv2.cvtColor(isma, cv2.COLOR_GRAY2BGR)
                elif ibig.shape[2] == 1 and isma.shape[2] == 3:
                    ibig = cv2.cvtColor(ibig, cv2.COLOR_GRAY2BGR)
            width = min(ibig.shape[1], isma.shape[1]) 
            ibig_resized = cv2.resize(ibig, (width, int(ibig.shape[0] * (width / ibig.shape[1])))) 
            isma_resized = cv2.resize(isma, (width, int(isma.shape[0] * (width / isma.shape[1]))))
            new_image = np.vstack((ibig_resized, isma_resized))
            cv2.imshow('Please click in order', new_image)
            cv2.setMouseCallback('Please click in order', mouse_callback)
            cv2.waitKey(0)
            return True, data
        else:
            success,data = self.det.check_target(ibig, isma)
            return success,data

    async def getAppAndMiniDetail(self, dataId, serviceType, p_uuid, token, sign, base_header, proxy="", session=None):
        """优化的详情获取，移除会话复用"""
        info = {"dataId": dataId, "serviceType": serviceType}
        length = str(len(str(ujson.dumps(info, ensure_ascii=False)).encode("utf-8")))

        detail_header = base_header.copy()
        detail_header.update({"Content-Length": length, "Uuid": p_uuid, "Token": token, "Sign": sign})

        if not getattr(getattr(config, 'captcha', object()), 'enable', False):
            detail_header.pop("Uuid", None)
            detail_header.pop("Content-Length", None)

        # 优先使用传入的会话，否则创建新会话
        if session:
            if getattr(getattr(config, 'captcha', object()), 'enable', False):
                async with session.post(self.queryDetailByAppAndMiniId,
                                        data=ujson.dumps(info, ensure_ascii=False),
                                        headers=detail_header,
                                        proxy=proxy if proxy else None) as req:
                    res = await req.text()
            else:
                async with session.post(f"{self.queryDetailByAppAndMiniId}",
                                        json=info,
                                        headers=detail_header,
                                        proxy=proxy if proxy else None) as req:
                    res = await req.text()
        else:
            async with self.get_session(proxy) as session:
                if getattr(getattr(config, 'captcha', object()), 'enable', False):
                    async with session.post(self.queryDetailByAppAndMiniId,
                                            data=ujson.dumps(info, ensure_ascii=False),
                                            headers=detail_header,
                                            proxy=proxy if proxy else None) as req:
                        res = await req.text()
                else:
                    async with session.post(f"{self.queryDetailByAppAndMiniId}",
                                            json=info,
                                            headers=detail_header,
                                            proxy=proxy if proxy else None) as req:
                        res = await req.text()
        return True, ujson.loads(res)

    async def getbeian(self, name, sp, pageNum, pageSize):
        info = ujson.loads(self.typj.get(sp))
        info["pageNum"] = pageNum
        info["pageSize"] = pageSize
        info["unitName"] = name
        
        if getattr(getattr(config, 'captcha', object()), 'enable', False):
            success, p_uuid, token, sign, base_header = await self.check_img()
            if not success:
                logger.info(f"打码失败：{p_uuid}")
                return False, p_uuid

            length = str(len(str(ujson.dumps(info, ensure_ascii=False)).encode("utf-8")))
            base_header.update({"Content-Length": length, "Uuid": p_uuid, "Token": token, "Sign": sign})
            
            proxy = self.proxy_manager.get_proxy()
            async with self.get_session(proxy) as session:
                async with session.post(self.queryByCondition,
                                        data=ujson.dumps(info, ensure_ascii=False),
                                        headers=base_header,
                                        proxy=proxy if proxy else None) as req:
                    res = await req.text()
        else:
            success, token, base_header = await self.get_token()
            sign = ""
            p_uuid = ""
            if not success:
                logger.info(f"获取token失败")
                return False, None
            base_header.update({"Token": token, "Sign": self.sign})

            proxy = self.proxy_manager.get_proxy()
            async with self.get_session(proxy) as session:
                current_ip = None
                if hasattr(session, '_connector') and hasattr(session._connector, '_local_addr'):
                    current_ip = session._connector._local_addr[0] if session._connector._local_addr else None
                async with session.post(f"{self.queryByCondition}/",
                                        json=info,
                                        headers=base_header,
                                        proxy=proxy if proxy else None) as req:
                    res = await req.text()

        if "当前访问疑似黑客攻击" in res:
            if current_ip:
                self._add_blocked_ip(current_ip)
            return False, "当前访问已被创宇盾拦截"
        
        result = ujson.loads(res)

        # 并发详情获取
        if (sp in (1, 2, 3)
            and result.get("success")
            and result.get("params", {}).get("list")):
            
            items = result["params"]["list"]
            if not items:
                return True, result
                
            logger.info(f"需要并发获取详细信息数量: {len(items)}")
            
            # 使用现有的detail_concurrency配置，默认值5
            max_concurrency = min(
                getattr(getattr(config, "system", object()), "detail_concurrency", 5),
                len(items),
                20  # 最大并发限制
            )
            sem = asyncio.Semaphore(max_concurrency)
            
            async def fetch_detail(item):
                if "dataId" not in item:
                    return item
                    
                serviceType = 6 if sp == 1 else (7 if sp == 2 else 8)
                try:
                    async with sem:
                        # 每个详情请求使用独立会话
                        d_success, d_data = await self.getAppAndMiniDetail(
                            item["dataId"], serviceType, p_uuid, token, 
                            sign if getattr(getattr(config, 'captcha', object()), 'enable', False) else self.sign, 
                            base_header, proxy
                        )
                    
                    if d_success and d_data.get("success"):
                        return d_data["params"]
                    else:
                        logger.warning(f"详情获取失败 dataId={item.get('dataId')}")
                        return item
                except Exception as e:
                    logger.error(f"详情获取异常 dataId={item.get('dataId')} err={e}")
                    return item

            # 分批处理，避免创建过多任务
            batch_size = max_concurrency * 2
            detailed_list = []
            
            for i in range(0, len(items), batch_size):
                batch = items[i:i + batch_size]
                tasks = [fetch_detail(item) for item in batch]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # 处理异常结果
                for j, res in enumerate(batch_results):
                    if isinstance(res, Exception):
                        logger.error(f"批次任务异常: {res}")
                        detailed_list.append(batch[j])  # 返回原始数据
                    else:
                        detailed_list.append(res)
            
            result["params"]["list"] = detailed_list
            logger.info(f"并发详情完成，总计 {len(detailed_list)} 条")
            
        return True, result

    async def getblackbeian(self, name, sp):
        info = ujson.loads(self.btypj.get(sp))
        if sp == 0:
            info["domainName"] = name
        else:
            info["serviceName"] = name


        if getattr(getattr(config, 'captcha', object()), 'enable', False):
            success, p_uuid, token, sign, base_header = await self.check_img()
            if not success:
                return False, p_uuid
            
            length = str(len(str(ujson.dumps(info, ensure_ascii=False)).encode("utf-8")))
            base_header.update(
                {"Content-Length": length, "Uuid": p_uuid, "Token": token, "Sign": sign}
            )
            proxy = self.proxy_manager.get_proxy()
            async with self.get_session(proxy) as session:
                current_ip = None
                if hasattr(session, '_connector') and hasattr(session._connector, '_local_addr'):
                    current_ip = session._connector._local_addr[0] if session._connector._local_addr else None
                async with session.post((self.blackqueryByCondition if sp == 0 else self.blackappAndMiniByCondition),
                                         data=ujson.dumps(info, ensure_ascii=False),
                                         headers=base_header, proxy=proxy if proxy else None) as req:
                    res = await req.text()
            
        else:
            success, token, base_header = await self.get_token()
            sign = ""
            p_uuid = ""
            if not success:
                logger.info(f"获取token失败")
                return False, None
            base_header.update({"Token": token, "Sign": self.sign})

            proxy = self.proxy_manager.get_proxy()
            async with self.get_session(proxy) as session:
                current_ip = None
                if hasattr(session, '_connector') and hasattr(session._connector, '_local_addr'):
                    current_ip = session._connector._local_addr[0] if session._connector._local_addr else None
                async with session.post((f"{self.blackqueryByCondition}/" if sp == 0 else f"{self.blackappAndMiniByCondition}/"),
                                            json=info, 
                                            headers=base_header, proxy=proxy if proxy else None) as req:
                    res = await req.text()

        if "当前访问疑似黑客攻击" in res:
            if current_ip:
                self._add_blocked_ip(current_ip)
            return False, "当前访问已被创宇盾拦截"

        return True,ujson.loads(res)

    async def autoget(self, name, sp, pageNum="", pageSize="", b=1):
        try:
            success,data = (
                await self.getbeian(name, sp, pageNum, pageSize)
                if b == 1
                else await self.getblackbeian(name, sp)
            )
            if not success:
                return {"code":500,"message":data}
            if data["code"] == 500 or not success:
                return {"code": 122, "message": "工信部服务器异常"}
        except Exception as e:
            return {"code": 122, "message": "查询失败","error":str(e)}
        
        return data

    # APP备案查询
    async def ymApp(self, name, pageNum="", pageSize=""):
        if not pageSize:
            pageSize = getattr(getattr(config, 'query', object()), 'default_page_size', 20)
        return await self.autoget(name, 1, pageNum, pageSize)

    # 网站备案查询
    async def ymWeb(self, name, pageNum="", pageSize=""):
        if not pageSize:
            pageSize = getattr(getattr(config, 'query', object()), 'default_page_size', 20)
        return await self.autoget(name, 0, pageNum, pageSize)

    # 小程序备案查询
    async def ymMiniApp(self, name, pageNum="", pageSize=""):
        if not pageSize:
            pageSize = getattr(getattr(config, 'query', object()), 'default_page_size', 20)
        return await self.autoget(name, 2, pageNum, pageSize)

    # 快应用备案查询
    async def ymKuaiApp(self, name, pageNum="", pageSize=""):
        if not pageSize:
            pageSize = getattr(getattr(config, 'query', object()), 'default_page_size', 20)
        return await self.autoget(name, 3, pageNum, pageSize)

    # 违法违规APP查询
    async def bymApp(self, name, pageNum="", pageSize=""):
        if not pageSize:
            pageSize = getattr(getattr(config, 'query', object()), 'default_page_size', 20)
        return await self.autoget(name, 1, pageNum, pageSize, b=0)

    # 违法违规网站查询
    async def bymWeb(self, name, pageNum="", pageSize=""):
        if not pageSize:
            pageSize = getattr(getattr(config, 'query', object()), 'default_page_size', 20)
        return await self.autoget(name, 0, pageNum, pageSize, b=0)

    # 违法违规小程序查询
    async def bymMiniApp(self, name, pageNum="", pageSize=""):
        if not pageSize:
            pageSize = getattr(getattr(config, 'query', object()), 'default_page_size', 20)
        return await self.autoget(name, 2, pageNum, pageSize, b=0)

    # 违法违规快应用查询
    async def bymKuaiApp(self, name, pageNum="", pageSize=""):
        if not pageSize:
            pageSize = getattr(getattr(config, 'query', object()), 'default_page_size', 20)
        return await self.autoget(name, 3, pageNum, pageSize, b=0)

    def cleanup(self):
        """清理资源并关闭事件循环"""
        if getattr(self, "_loop", None):
            if not self._loop.is_closed():
                self._loop.close()
        logger.info("beian资源清理完成")

if __name__ == "__main__":
    async def main():
        a = beian()
        try:
            # 官方单页查询pageSize最大支持26
            # 页面索引pageNum从1开始,第一页可以不写
            data = await a.ymWeb("深圳市腾讯计算机系统有限公司")
            print(f"查询结果：\n{data}")
            data = await a.ymApp("深圳市腾讯计算机系统有限公司")
            print(f"查询结果：\n{data}")
        finally:
            a.cleanup()  # 确保资源清理

    asyncio.run(main())

    """
    在其他代码模块中调用（异步）

        from ymicp import beian

        icp = beian()
        try:
            data = await icp.ymApp("微信")
        finally:
            icp.cleanup()  # 重要：确保资源清理
    
    """
