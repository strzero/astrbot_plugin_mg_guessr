from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import data_manager  # 引入 data_manager 模块


@register("mg-guessr", "Star0", "mg-guessr-extention", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        """插件初始化时会自动调用"""
        url = "https://arcwiki.mcd.blue/index.php?title=Template:Songlist.json&action=raw"

        # 异步获取曲目信息
        song_data = await data_manager.fetch_song_data(url)

        if song_data:
            # 获取别名数据
            aliases = await data_manager.fetch_aliases()
            # 存储数据到数据库
            data_manager.store_data_in_db(song_data, aliases)
            logger.info("数据初始化并存储成功。")
        else:
            logger.error("无法获取有效的曲目信息，初始化失败。")

    @filter.command("mg")
    async def helloworld(self, event: AstrMessageEvent):
        """这是一个 hello world 指令"""
        user_name = event.get_sender_name()
        message_str = event.message_str
        message_chain = event.get_messages()
        logger.info(message_chain)
        yield event.plain_result(f"Hello, {user_name}, 你发了 {message_str}!")

    async def terminate(self):
        """插件被卸载/停用时会调用"""
        pass
