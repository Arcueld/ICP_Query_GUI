import yaml
import os


def init_application():
    """初始化应用程序，确保必要的文件和目录存在"""
    # 确保必要的目录存在
    directories = ["logs"]
    for directory in directories:
        if not os.path.exists(directory):
            try:
                os.makedirs(directory, exist_ok=True)
                print(f"已创建目录: {directory}")
            except Exception as e:
                print(f"创建目录 {directory} 失败: {e}")

    # 检查配置文件是否存在
    if not os.path.exists("config.yml"):
        print("配置文件 config.yml 不存在，正在创建默认配置文件...")
        return create_default_config()
    return True


def create_default_config():
    """创建默认配置文件"""
    default_config = {
        "captcha": {
            "captcha_retry_times": 5,
            "device": ["CUDA"],
            "enable": True,
            "proxy_retry_delay": 1,
            "save_failed_img": False,
            "save_failed_img_path": "",
        },
        "log": {
            "backup_count": 7,
            "dir": "logs",
            "file_head": "ymicp",
            "output_console": True,
            "save_log": False,
        },
        "proxy": {
            "extra_api": {
                "auto_maintenace": True,
                "check_proxy": True,
                "check_proxy_num": 20,
                "enable": False,
                "extra_interval": 3,
                "pool_num": 100,
                "proxy_timeout": 0.5,
                "timeout": 100,
                "timeout_drop": 8,
                "url": None,
            },
            "static_proxy": {
                "enable": False,
                "host": "127.0.0.1",
                "password": "",
                "port": 8800,
                "type": "http",
                "username": "",
            },
        },
        "query": {
            "captcha_retry_times": 5,
            "coding_code": "auto",
            "coding_show": False,
            "default_page_size": 20,
            "max_page_size": 100,
            "proxy_retry_delay": 1,
            "retry_times": 2,
            "risk_delay_enable": False,
            "risk_delay_seconds": 1,
        },
        "risk_avoidance": {
            "allow_type": [
                "web",
                "app",
                "mapp",
                "kapp",
                "bweb",
                "bapp",
                "bmapp",
                "bkapp",
            ],
            "prohibit_suffix": [],
        },
        "system": {
            "detail_concurrency": 5,
            "host": "0.0.0.0",
            "http_client_timeout": 5,
            "port": 16181,
            "web_ui": True,
        },
    }

    try:
        with open("config.yml", "w", encoding="utf-8") as file:
            yaml.dump(
                default_config,
                file,
                default_flow_style=False,
                allow_unicode=True,
                indent=2,
            )
        print("已创建默认配置文件 config.yml")
        return True
    except Exception as e:
        print(f"创建默认配置文件失败: {e}")
        return False


# 初始化应用程序
init_application()

try:

    class Config:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                # 如果值是字典，则递归转换为对象
                if isinstance(value, dict):
                    value = Config(**value)
                setattr(self, key, value)

        def __repr__(self):
            return str(self.__dict__)

        def __getattr__(self, name):
            return None

    def load_config(file_path):
        with open(file_path, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file)

        return Config(**data)

    config = load_config("config.yml")
    print("配置文件加载成功")
except FileNotFoundError:
    print("配置文件 config.yml 不存在，正在创建默认配置文件...")
    if create_default_config():
        try:
            config = load_config("config.yml")
            print("默认配置文件创建成功并已加载")
        except Exception as e:
            print(f"加载默认配置文件失败: {e}")
            import sys

            sys.exit()
    else:
        print("无法创建默认配置文件，程序退出")
        import sys

        sys.exit()
except yaml.YAMLError as e:
    print(f"配置文件格式错误: {e}")
    import sys

    sys.exit()
except Exception as e:
    print(f"加载配置文件失败: {e}")
    import sys

    sys.exit()
