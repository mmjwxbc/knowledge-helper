import srt
import yaml
from xhs_downloader.application.app import XHS
import os

def read_srt(content):        
    subtitles = list(srt.parse(content))
    
    subs = [sub.content for sub in subtitles]
    return "\n".join(subs)        



class XHSClientManager:
    _instance = None

    @classmethod
    def get_config(cls, config_path="config.yaml"):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return config
    
async def init_xhs():
    config_params = XHSClientManager.get_config("/home/jhli/knowledge-helper/config/xhs.yaml")    
    return XHS(**config_params)


def list_dir(id: str):
    # flat absolute path
    directory = os.path.abspath(os.path.join("/home/jhli/knowledge-helper/output/xhs/download", id, id))
    return [os.path.join(directory, item) for item in os.listdir(directory)]
