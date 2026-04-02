import asyncio
import aiohttp
import cv2
import time
import hashlib
import re
import base64
import io
import os
import numpy as np
import ujson
import uuid
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from PIL import Image
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
        self.proxy_config = getattr(config, "proxy", object())
        self.static_proxy = None
        self._init_static_proxy()

    def _init_static_proxy(self):
        """初始化静态代理配置"""
        static_config = getattr(self.proxy_config, "static_proxy", object())
        if getattr(static_config, "enable", False):
            proxy_type = getattr(static_config, "type", "http")
            host = getattr(static_config, "host", "")
            port = getattr(static_config, "port", 0)
            username = getattr(static_config, "username", "")
            password = getattr(static_config, "password", "")

            # 只支持 HTTP/HTTPS 代理
            if proxy_type not in ["http", "https"]:
                logger.error(f"不支持的代理类型: {proxy_type}，只支持 http 和 https")
                return

            if host and port:
                if username and password:
                    self.static_proxy = (
                        f"{proxy_type}://{username}:{password}@{host}:{port}"
                    )
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
        if getattr(getattr(self.proxy_config, "extra_api", object()), "enable", False):
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
        base_timeout = getattr(
            getattr(config, "system", object()), "http_client_timeout", 30
        )
        self.timeout = aiohttp.ClientTimeout(
            total=base_timeout * 2,  # 总超时时间翻倍
            connect=base_timeout,  # 连接超时
            sock_read=base_timeout,  # 读取超时
            sock_connect=base_timeout,  # socket连接超时
        )
        self.check_image_timeout = aiohttp.ClientTimeout(
            total=80,
            connect=80,
            sock_read=80,
            sock_connect=80,
        )

        # 连接池配置
        self.connector_config = {
            "limit": 100,
            "limit_per_host": 30,
            "ttl_dns_cache": 300,
            "use_dns_cache": True,
            "ssl": False,
            "keepalive_timeout": 60,
        }

        self._blocked_ip_cache = TTLCache(maxsize=1000, ttl=300)
        self._blocked_ip_lock = threading.Lock()

        # 初始化代理管理器
        self.proxy_manager = ProxyManager()

    async def _apply_risk_delay(self, scene="查询请求"):
        query_config = getattr(config, "query", object())
        delay_enabled = bool(getattr(query_config, "risk_delay_enable", False))
        delay_seconds = getattr(query_config, "risk_delay_seconds", 0)

        try:
            delay_value = float(delay_seconds)
        except (TypeError, ValueError):
            delay_value = 0

        if delay_enabled and delay_value > 0:
            logger.info(f"风控延时已开启，{scene}前等待 {delay_value} 秒")
            await asyncio.sleep(delay_value)

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
            headers={"Connection": "keep-alive"},
        )

        try:
            yield session
        finally:
            # 确保session和connector都被正确关闭
            await session.close()
            await connector.close()

    async def get_token(self):
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
                if hasattr(session, "_connector") and hasattr(
                    session._connector, "_local_addr"
                ):
                    current_ip = (
                        session._connector._local_addr[0]
                        if session._connector._local_addr
                        else None
                    )
                async with session.post(
                    self.url,
                    data=auth_data,
                    headers=base_header,
                    proxy=proxy if proxy else None,
                ) as req:
                    req_text = await req.text()

            if "当前访问疑似黑客攻击" in req_text:
                if current_ip:
                    self._add_blocked_ip(current_ip)
                return False, "当前访问已被创宇盾拦截", ""

            try:
                t = ujson.loads(req_text)
                token = t["params"]["bussiness"]
                expire = int(time.time() * 1000) + t["params"]["expire"]
            except (KeyError, ValueError, TypeError) as e:
                logger.error(f"解析token响应失败: {e}, 响应内容: {req_text[:200]}")
                return False, f"解析token响应失败: {e}", ""

            self.token = token
            self.token_expire = expire

            return True, token, base_header
        except Exception as e:
            logger.error(f"get_token Faile : {e}")
            return False, str(e), ""

    async def get_cookie(self):
        proxy = self.proxy_manager.get_proxy()
        async with self.get_session(proxy) as session:
            async with session.get(
                self.home, headers=self.cookie_headers, proxy=proxy if proxy else None
            ) as req:
                res = await req.text()
                cookie_match = re.compile("[0-9a-z]{32}").search(str(req.cookies))
                if cookie_match:
                    return cookie_match[0]
                return None

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

    def match_slider_offset(self, small_image_b64, big_image_b64):
        big_img = np.array(
            Image.open(io.BytesIO(base64.b64decode(big_image_b64))).convert("RGB")
        )
        small_img = np.array(Image.open(io.BytesIO(base64.b64decode(small_image_b64))))
        sh, sw = small_img.shape[:2]

        resized = big_img[::2, ::2]
        h, w = resized.shape[:2]
        min_side = int(min(sw, sh) * 0.25)

        q = (resized.astype(np.int32) // 4) * 4
        color_id = q[:, :, 0] + q[:, :, 1] * 256 + q[:, :, 2] * 65536

        flat_colors = color_id.ravel()
        unique, counts = np.unique(flat_colors, return_counts=True)
        top_indices = np.argsort(counts)[-5:]

        best_area = 0
        best_x = 0

        for idx in top_indices:
            color = unique[idx]
            mask = color_id == color
            col_run = np.zeros((h, w), dtype=np.int32)
            col_run[0] = mask[0].astype(np.int32)

            for y in range(1, h):
                col_run[y] = np.where(mask[y], col_run[y - 1] + 1, 0)

            for y in range(min_side, h):
                row = col_run[y] >= min_side
                if not np.any(row):
                    continue

                diff = np.diff(row.astype(np.int8))
                starts = np.where(diff == 1)[0] + 1
                ends = np.where(diff == -1)[0] + 1
                if row[0]:
                    starts = np.concatenate([[0], starts])
                if row[-1]:
                    ends = np.concatenate([ends, [w]])

                for start_x, end_x in zip(starts, ends):
                    run_w = end_x - start_x
                    if start_x <= sw // 4:
                        continue

                    run_h = int(col_run[y, start_x])
                    ratio = run_w / run_h if run_h > 0 else 0
                    if 0.7 < ratio < 1.4 and run_w * run_h > best_area:
                        best_area = run_w * run_h
                        best_x = start_x

        if best_area == 0:
            return False, "未找到滑块缺口"

        offset_x = best_x * 2
        logger.info(f"滑块缺口定位成功: x={offset_x}, 滑块尺寸={sw}x{sh}")
        return True, offset_x

    def _extract_sign(self, data):
        params = data.get("params")
        if isinstance(params, dict):
            return params.get("sign", "")
        return params or ""

    def _is_proxy_error(self, error_msg):
        """
        判断是否为代理质量问题导致的错误

        Args:
            error_msg: 错误信息（字符串或异常对象）

        Returns:
            bool: 如果是代理错误返回True，否则返回False
        """
        if not error_msg:
            return False

        error_str = str(error_msg).lower()
        proxy_error_keywords = [
            "server disconnected",
            "connection",
            "timeout",
            "connection reset",
            "connection aborted",
            "connection refused",
            "proxy",
            "connector",
            "socket",
            "network",
            "unreachable",
            "reset by peer",
        ]

        return any(keyword in error_str for keyword in proxy_error_keywords)

    async def check_img(self, max_retries=None):
        """
        验证码识别，支持多次重试
        代理质量问题导致的失败不计入重试次数，会立即切换代理重试

        Args:
            max_retries: 最大重试次数 从配置文件读取

        Returns:
            tuple: (success, result, token, sign, base_header)
        """
        if max_retries is None:
            max_retries = getattr(
                getattr(config, "captcha", object()), "captcha_retry_times", 5
            )

        proxy_retry_limit = 5  # 每个主重试最多尝试的代理数量

        for attempt in range(max_retries):
            try:
                logger.info(f"验证码识别尝试 {attempt + 1}/{max_retries}")

                proxy_retry_count = 0
                success = False
                token = None
                base_header = None

                while proxy_retry_count < proxy_retry_limit:
                    try:
                        success, token, base_header = await self.get_token()
                        if not success:
                            error_msg = token if isinstance(token, str) else str(token)
                            if self._is_proxy_error(error_msg):
                                proxy_retry_count += 1
                                logger.warning(
                                    f"代理错误（不计入重试次数），切换代理重试 {proxy_retry_count}/{proxy_retry_limit}: {error_msg}"
                                )
                                await asyncio.sleep(0.5)  # 短暂等待后切换代理
                                continue
                            else:
                                # 非代理错误，计入主重试次数
                                if attempt == max_retries - 1:
                                    return False, token, "", "", ""

                                proxy_config = getattr(config, "proxy", object())
                                captcha_config = getattr(config, "captcha", object())
                                extra_api_config = getattr(
                                    proxy_config, "extra_api", object()
                                )
                                if getattr(
                                    extra_api_config, "enable", False
                                ) and getattr(
                                    extra_api_config, "auto_maintenace", False
                                ):
                                    delay = getattr(
                                        captcha_config, "proxy_retry_delay", 1
                                    )
                                    logger.info(
                                        f"检测到代理池已启用，等待{delay}秒后重试..."
                                    )
                                    await asyncio.sleep(delay)

                                break

                        # 成功获取token，跳出代理重试循环
                        break
                    except Exception as e:
                        if self._is_proxy_error(e):
                            proxy_retry_count += 1
                            logger.warning(
                                f"代理错误（不计入重试次数），切换代理重试 {proxy_retry_count}/{proxy_retry_limit}: {e}"
                            )
                            await asyncio.sleep(0.5)
                            continue
                        else:
                            raise

                if proxy_retry_count >= proxy_retry_limit:
                    logger.error(
                        f"代理重试次数已达上限 {proxy_retry_limit}，计入主重试次数"
                    )
                    if attempt == max_retries - 1:
                        return False, "代理连接失败，已尝试多个代理", "", "", ""
                    continue

                if not success:
                    continue

                data = self.get_clientUid()
                clientUid = ujson.loads(data)["clientUid"]
                length = str(len(str(data).encode("utf-8")))
                base_header.update(
                    {
                        "Content-Length": length,
                        "token": token,
                    }
                )
                base_header["Content-Type"] = "application/json"

                proxy_retry_count = 0
                res = None
                while proxy_retry_count < proxy_retry_limit:
                    try:
                        proxy = self.proxy_manager.get_proxy()
                        async with self.get_session(proxy) as session:
                            async with session.post(
                                self.getCheckImage,
                                data=data,
                                headers=base_header,
                                timeout=self.check_image_timeout,
                                proxy=proxy if proxy else None,
                            ) as req:
                                res = await req.json()
                        break
                    except Exception as e:
                        if self._is_proxy_error(e):
                            proxy_retry_count += 1
                            logger.warning(
                                f"请求验证码时代理错误（不计入重试次数），切换代理重试 {proxy_retry_count}/{proxy_retry_limit}: {e}"
                            )
                            await asyncio.sleep(0.5)
                            continue
                        else:
                            logger.warning(f"请求验证码时失败：{e}")
                            if attempt == max_retries - 1:
                                return False, f"请求验证码时失败：{e}", "", "", ""

                            proxy_config = getattr(config, "proxy", object())
                            captcha_config = getattr(config, "captcha", object())
                            extra_api_config = getattr(
                                proxy_config, "extra_api", object()
                            )
                            if getattr(extra_api_config, "enable", False) and getattr(
                                extra_api_config, "auto_maintenace", False
                            ):
                                delay = getattr(captcha_config, "proxy_retry_delay", 1)
                                logger.info(
                                    f"检测到代理池已启用，等待{delay}秒后重试..."
                                )
                                await asyncio.sleep(delay)

                            break

                if proxy_retry_count >= proxy_retry_limit:
                    logger.error(
                        f"请求验证码时代理重试次数已达上限 {proxy_retry_limit}，计入主重试次数"
                    )
                    if attempt == max_retries - 1:
                        return (
                            False,
                            "请求验证码时代理连接失败，已尝试多个代理",
                            "",
                            "",
                            "",
                        )
                    continue

                if res is None:
                    logger.error("请求验证码失败，响应为空")
                    if attempt == max_retries - 1:
                        return False, "请求验证码失败，响应为空", "", "", ""
                    continue

                captcha_params = res["params"]
                p_uuid = captcha_params["uuid"]
                big_image = captcha_params["bigImage"]
                small_image = captcha_params["smallImage"]

                use_slider = "secretKey" not in captcha_params
                if use_slider:
                    start = time.time()
                    success, slider_offset = self.match_slider_offset(
                        small_image, big_image
                    )
                    if not success:
                        logger.warning(f"滑块匹配失败：{slider_offset}")
                        if attempt == max_retries - 1:
                            return False, "slider_offset", "", "", ""
                        continue

                    logger.info(f"滑块匹配用时 {time.time() - start} s")
                    data = ujson.dumps({"key": p_uuid, "value": str(slider_offset)})
                    length = str(len(data.encode("utf-8")))
                    base_header.update({"Content-Length": length})
                    request_kwargs = {"data": data}
                else:
                    secretKey = captcha_params["secretKey"]

                    start = time.time()
                    success, selice_small = await self.small_selice(
                        small_image, big_image
                    )
                    if not success:
                        logger.warning(f"验证码切割失败：{selice_small}")
                        if attempt == max_retries - 1:
                            return False, "selice_small", "", "", ""

                        proxy_config = getattr(config, "proxy", object())
                        captcha_config = getattr(config, "captcha", object())
                        extra_api_config = getattr(proxy_config, "extra_api", object())
                        if getattr(extra_api_config, "enable", False) and getattr(
                            extra_api_config, "auto_maintenace", False
                        ):
                            delay = getattr(captcha_config, "proxy_retry_delay", 1)
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
                    request_kwargs = {"json": data}

                proxy_retry_count = 0
                res = None
                while proxy_retry_count < proxy_retry_limit:
                    try:
                        proxy = self.proxy_manager.get_proxy()
                        async with self.get_session(proxy) as session:
                            async with session.post(
                                self.checkImage,
                                headers=base_header,
                                proxy=proxy if proxy else None,
                                **request_kwargs,
                            ) as req:
                                res = await req.text()
                        break
                    except Exception as e:
                        if self._is_proxy_error(e):
                            proxy_retry_count += 1
                            logger.warning(
                                f"提交验证码结果时代理错误（不计入重试次数），切换代理重试 {proxy_retry_count}/{proxy_retry_limit}: {e}"
                            )
                            await asyncio.sleep(0.5)
                            continue
                        else:
                            raise

                if proxy_retry_count >= proxy_retry_limit:
                    logger.error(
                        f"提交验证码结果时代理重试次数已达上限 {proxy_retry_limit}，计入主重试次数"
                    )
                    if attempt == max_retries - 1:
                        return (
                            False,
                            "提交验证码结果时代理连接失败，已尝试多个代理",
                            "",
                            "",
                            "",
                        )
                    continue

                data = ujson.loads(res)
                if data["success"] == False:
                    logger.warning(f"验证码识别失败，尝试 {attempt + 1}/{max_retries}")

                    if attempt == max_retries - 1:
                        return False, "验证码识别失败", "", "", ""

                    proxy_config = getattr(config, "proxy", object())
                    captcha_config = getattr(config, "captcha", object())
                    extra_api_config = getattr(proxy_config, "extra_api", object())
                    if getattr(extra_api_config, "enable", False) and getattr(
                        extra_api_config, "auto_maintenace", False
                    ):
                        delay = getattr(captcha_config, "proxy_retry_delay", 1)
                        logger.info(f"检测到代理池已启用，等待{delay}秒后重试...")
                        await asyncio.sleep(delay)

                    continue
                else:
                    logger.info(f"验证码识别成功，尝试次数：{attempt + 1}")
                    return True, p_uuid, token, self._extract_sign(data), base_header

            except Exception as e:
                if self._is_proxy_error(e):
                    logger.warning(
                        f"验证码识别时代理错误（不计入重试次数），切换代理重试: {e}"
                    )
                    await asyncio.sleep(0.5)
                    continue

                logger.error(f"验证码识别异常，尝试 {attempt + 1}/{max_retries}：{e}")
                if attempt == max_retries - 1:
                    return False, f"验证码识别异常：{e}", "", "", ""

                proxy_config = getattr(config, "proxy", object())
                extra_api_config = getattr(proxy_config, "extra_api", object())
                if getattr(extra_api_config, "enable", False) and getattr(
                    extra_api_config, "auto_maintenace", False
                ):
                    logger.info("检测到代理池已启用，等待1秒后重试...")
                    await asyncio.sleep(1)

                continue

        return False, "验证码识别失败，已达到最大重试次数", "", "", ""

    async def small_selice(self, small_image, big_image):
        isma = cv2.imdecode(
            np.frombuffer(base64.b64decode(small_image), np.uint8), cv2.COLOR_GRAY2RGB
        )

        isma = cv2.cvtColor(isma, cv2.COLOR_BGRA2BGR)
        ibig = cv2.imdecode(
            np.frombuffer(base64.b64decode(big_image), np.uint8), cv2.COLOR_GRAY2RGB
        )

        captcha_config = getattr(config, "captcha", object())
        if getattr(captcha_config, "coding_code", "auto") == "labour":

            def mouse_callback(event, x, y, flags, param):
                if event == cv2.EVENT_LBUTTONDOWN:
                    data.append({"x": x, "y": y})
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
            ibig_resized = cv2.resize(
                ibig, (width, int(ibig.shape[0] * (width / ibig.shape[1])))
            )
            isma_resized = cv2.resize(
                isma, (width, int(isma.shape[0] * (width / isma.shape[1])))
            )
            new_image = np.vstack((ibig_resized, isma_resized))
            cv2.imshow("Please click in order", new_image)
            cv2.setMouseCallback("Please click in order", mouse_callback)
            cv2.waitKey(0)
            return True, data
        else:
            success, data = self.det.check_target(ibig, isma)
            return success, data

    async def getAppAndMiniDetail(
        self,
        dataId,
        serviceType,
        p_uuid,
        token,
        sign,
        base_header,
        proxy="",
        session=None,
    ):
        """优化的详情获取，移除会话复用"""
        info = {"dataId": dataId, "serviceType": serviceType}
        length = str(len(str(ujson.dumps(info, ensure_ascii=False)).encode("utf-8")))

        detail_header = base_header.copy()
        detail_header.update(
            {
                "Content-Length": length,
                "uuid": p_uuid,
                "token": token,
                "sign": sign,
            }
        )

        if not getattr(getattr(config, "captcha", object()), "enable", False):
            detail_header.pop("uuid", None)
            detail_header.pop("Content-Length", None)

        # 优先使用传入的会话，否则创建新会话
        if session:
            if getattr(getattr(config, "captcha", object()), "enable", False):
                async with session.post(
                    self.queryDetailByAppAndMiniId,
                    data=ujson.dumps(info, ensure_ascii=False),
                    headers=detail_header,
                    proxy=proxy if proxy else None,
                ) as req:
                    res = await req.text()
            else:
                async with session.post(
                    f"{self.queryDetailByAppAndMiniId}",
                    json=info,
                    headers=detail_header,
                    proxy=proxy if proxy else None,
                ) as req:
                    res = await req.text()
        else:
            async with self.get_session(proxy) as session:
                if getattr(getattr(config, "captcha", object()), "enable", False):
                    async with session.post(
                        self.queryDetailByAppAndMiniId,
                        data=ujson.dumps(info, ensure_ascii=False),
                        headers=detail_header,
                        proxy=proxy if proxy else None,
                    ) as req:
                        res = await req.text()
                else:
                    async with session.post(
                        f"{self.queryDetailByAppAndMiniId}",
                        json=info,
                        headers=detail_header,
                        proxy=proxy if proxy else None,
                    ) as req:
                        res = await req.text()
        return True, ujson.loads(res)

    async def getbeian(self, name, sp, pageNum, pageSize):
        await self._apply_risk_delay("备案查询")
        info = ujson.loads(self.typj.get(sp))
        info["pageNum"] = pageNum
        info["pageSize"] = pageSize
        info["unitName"] = name

        current_ip = None
        res = None

        if getattr(getattr(config, "captcha", object()), "enable", False):
            success, p_uuid, token, sign, base_header = await self.check_img()
            if not success:
                logger.info(f"打码失败：{p_uuid}")
                return False, p_uuid

            length = str(
                len(str(ujson.dumps(info, ensure_ascii=False)).encode("utf-8"))
            )
            base_header.update(
                {
                    "Content-Length": length,
                    "uuid": p_uuid,
                    "token": token,
                    "sign": sign,
                }
            )

            proxy = self.proxy_manager.get_proxy()
            async with self.get_session(proxy) as session:
                if hasattr(session, "_connector") and hasattr(
                    session._connector, "_local_addr"
                ):
                    current_ip = (
                        session._connector._local_addr[0]
                        if session._connector._local_addr
                        else None
                    )
                async with session.post(
                    self.queryByCondition,
                    data=ujson.dumps(info, ensure_ascii=False),
                    headers=base_header,
                    proxy=proxy if proxy else None,
                ) as req:
                    res = await req.text()
        else:
            success, token, base_header = await self.get_token()
            sign = ""
            p_uuid = ""
            if not success:
                logger.info(f"获取token失败")
                return False, None
            base_header.update(
                {
                    "token": token,
                    "sign": self.sign,
                }
            )

            proxy = self.proxy_manager.get_proxy()
            async with self.get_session(proxy) as session:
                if hasattr(session, "_connector") and hasattr(
                    session._connector, "_local_addr"
                ):
                    current_ip = (
                        session._connector._local_addr[0]
                        if session._connector._local_addr
                        else None
                    )
                async with session.post(
                    f"{self.queryByCondition}/",
                    json=info,
                    headers=base_header,
                    proxy=proxy if proxy else None,
                ) as req:
                    res = await req.text()

        if not res:
            return False, "请求失败，响应为空"

        if "当前访问疑似黑客攻击" in res:
            if current_ip:
                self._add_blocked_ip(current_ip)
            return False, "当前访问已被创宇盾拦截"

        try:
            result = ujson.loads(res)
        except (ValueError, TypeError) as e:
            logger.error(
                f"解析查询结果失败: {e}, 响应内容: {res[:200] if res else 'None'}"
            )
            return False, f"解析查询结果失败: {e}"

        # 并发详情获取
        if (
            sp in (1, 2, 3)
            and result.get("success")
            and result.get("params", {}).get("list")
        ):
            items = result["params"]["list"]
            if not items:
                return True, result

            logger.info(f"需要并发获取详细信息数量: {len(items)}")

            # 使用现有的detail_concurrency配置，默认值5
            max_concurrency = min(
                getattr(getattr(config, "system", object()), "detail_concurrency", 5),
                len(items),
                20,  # 最大并发限制
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
                            item["dataId"],
                            serviceType,
                            p_uuid,
                            token,
                            sign
                            if getattr(
                                getattr(config, "captcha", object()), "enable", False
                            )
                            else self.sign,
                            base_header,
                            proxy,
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
                batch = items[i : i + batch_size]
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
        await self._apply_risk_delay("黑名单查询")
        info = ujson.loads(self.btypj.get(sp))
        if sp == 0:
            info["domainName"] = name
        else:
            info["serviceName"] = name

        current_ip = None
        res = None

        if getattr(getattr(config, "captcha", object()), "enable", False):
            success, p_uuid, token, sign, base_header = await self.check_img()
            if not success:
                return False, p_uuid

            length = str(
                len(str(ujson.dumps(info, ensure_ascii=False)).encode("utf-8"))
            )
            base_header.update(
                {
                    "Content-Length": length,
                    "uuid": p_uuid,
                    "token": token,
                    "sign": sign,
                }
            )
            proxy = self.proxy_manager.get_proxy()
            async with self.get_session(proxy) as session:
                if hasattr(session, "_connector") and hasattr(
                    session._connector, "_local_addr"
                ):
                    current_ip = (
                        session._connector._local_addr[0]
                        if session._connector._local_addr
                        else None
                    )
                async with session.post(
                    (
                        self.blackqueryByCondition
                        if sp == 0
                        else self.blackappAndMiniByCondition
                    ),
                    data=ujson.dumps(info, ensure_ascii=False),
                    headers=base_header,
                    proxy=proxy if proxy else None,
                ) as req:
                    res = await req.text()

        else:
            success, token, base_header = await self.get_token()
            sign = ""
            p_uuid = ""
            if not success:
                logger.info(f"获取token失败")
                return False, None
            base_header.update(
                {
                    "token": token,
                    "sign": self.sign,
                }
            )

            proxy = self.proxy_manager.get_proxy()
            async with self.get_session(proxy) as session:
                if hasattr(session, "_connector") and hasattr(
                    session._connector, "_local_addr"
                ):
                    current_ip = (
                        session._connector._local_addr[0]
                        if session._connector._local_addr
                        else None
                    )
                async with session.post(
                    (
                        f"{self.blackqueryByCondition}/"
                        if sp == 0
                        else f"{self.blackappAndMiniByCondition}/"
                    ),
                    json=info,
                    headers=base_header,
                    proxy=proxy if proxy else None,
                ) as req:
                    res = await req.text()

        if not res:
            return False, "请求失败，响应为空"

        if "当前访问疑似黑客攻击" in res:
            if current_ip:
                self._add_blocked_ip(current_ip)
            return False, "当前访问已被创宇盾拦截"

        try:
            return True, ujson.loads(res)
        except (ValueError, TypeError) as e:
            logger.error(
                f"解析黑名单查询结果失败: {e}, 响应内容: {res[:200] if res else 'None'}"
            )
            return False, f"解析黑名单查询结果失败: {e}"

    async def autoget(self, name, sp, pageNum="", pageSize="", b=1):
        try:
            success, data = (
                await self.getbeian(name, sp, pageNum, pageSize)
                if b == 1
                else await self.getblackbeian(name, sp)
            )
            if not success:
                return {"code": 500, "message": data}
            if data["code"] == 500 or not success:
                return {"code": 122, "message": "工信部服务器异常"}
        except Exception as e:
            return {"code": 122, "message": "查询失败", "error": str(e)}

        return data

    # APP备案查询
    async def ymApp(self, name, pageNum="", pageSize=""):
        if not pageSize:
            pageSize = getattr(
                getattr(config, "query", object()), "default_page_size", 20
            )
        return await self.autoget(name, 1, pageNum, pageSize)

    # 网站备案查询
    async def ymWeb(self, name, pageNum="", pageSize=""):
        if not pageSize:
            pageSize = getattr(
                getattr(config, "query", object()), "default_page_size", 20
            )
        return await self.autoget(name, 0, pageNum, pageSize)

    # 小程序备案查询
    async def ymMiniApp(self, name, pageNum="", pageSize=""):
        if not pageSize:
            pageSize = getattr(
                getattr(config, "query", object()), "default_page_size", 20
            )
        return await self.autoget(name, 2, pageNum, pageSize)

    # 快应用备案查询
    async def ymKuaiApp(self, name, pageNum="", pageSize=""):
        if not pageSize:
            pageSize = getattr(
                getattr(config, "query", object()), "default_page_size", 20
            )
        return await self.autoget(name, 3, pageNum, pageSize)

    # 违法违规APP查询
    async def bymApp(self, name, pageNum="", pageSize=""):
        if not pageSize:
            pageSize = getattr(
                getattr(config, "query", object()), "default_page_size", 20
            )
        return await self.autoget(name, 1, pageNum, pageSize, b=0)

    # 违法违规网站查询
    async def bymWeb(self, name, pageNum="", pageSize=""):
        if not pageSize:
            pageSize = getattr(
                getattr(config, "query", object()), "default_page_size", 20
            )
        return await self.autoget(name, 0, pageNum, pageSize, b=0)

    # 违法违规小程序查询
    async def bymMiniApp(self, name, pageNum="", pageSize=""):
        if not pageSize:
            pageSize = getattr(
                getattr(config, "query", object()), "default_page_size", 20
            )
        return await self.autoget(name, 2, pageNum, pageSize, b=0)

    # 违法违规快应用查询
    async def bymKuaiApp(self, name, pageNum="", pageSize=""):
        if not pageSize:
            pageSize = getattr(
                getattr(config, "query", object()), "default_page_size", 20
            )
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
