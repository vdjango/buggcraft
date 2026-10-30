import os
import tempfile

# 使用轻量的 png 库代替 Pillow
import png
from utils.network import minecraft_httpx

import logging
logger = logging.getLogger(__name__)


def download_skin(url):
    """从URL下载Minecraft皮肤图片"""
    return minecraft_httpx.download(url)


def extract_minecraft_head(skin_data, output_path=None, scale_factor=10):
    """
    从Minecraft皮肤数据中提取头部头像 (使用pypng库)
    
    Args:
        skin_data (bytes): 皮肤图片的二进制数据
        output_path (str, optional): 输出头像的路径
        scale_factor (int): 放大倍数
        
    Returns:
        str: 保存的输出文件路径
        
    Raises:
        Exception: 如果处理过程中发生错误
    """
    # 创建临时文件保存皮肤数据
    from utils.storage_paths import temporary_directory, cache_directory
    with tempfile.NamedTemporaryFile(delete=False, suffix='.png', dir=temporary_directory()) as temp_file:
        temp_file.write(skin_data)
        temp_path = temp_file.name

    try:
        # 使用png库读取PNG图像
        reader = png.Reader(filename=temp_path)
        width, height, rows, metadata = reader.read()
        
        # 将像素数据转换为平面数组以便处理
        pixels = []
        for row in rows:
            pixels.extend(row)
        
        # 计算每个像素的字节数
        if 'alpha' in metadata and metadata['alpha']:
            bytes_per_pixel = 4  # RGBA
        else:
            bytes_per_pixel = 3  # RGB

        # 定义标准皮肤尺寸和对应的头部坐标
        if (width, height) == (64, 32):
            # 旧版皮肤 64x32
            head_coords = (8, 8, 16, 16)
        elif (width, height) == (64, 64):
            # 标准皮肤 64x64
            head_coords = (8, 8, 16, 16)
        elif (width, height) == (128, 128):
            # 高清皮肤 128x128
            head_coords = (16, 16, 32, 32)
        elif (width, height) == (256, 256):
            # 超清皮肤 256x256
            head_coords = (32, 32, 64, 64)
        else:
            # 非标准尺寸，按比例计算
            ratio = width / 64
            head_coords = (
                int(8 * ratio), 
                int(8 * ratio), 
                int(16 * ratio), 
                int(16 * ratio)
            )

        x1, y1, x2, y2 = head_coords
        head_width = x2 - x1
        head_height = y2 - y1
        
        # 提取头部像素数据
        head_pixels = []
        for y in range(y1, y2):
            row_start = y * width * bytes_per_pixel
            pixel_start = row_start + x1 * bytes_per_pixel
            pixel_end = row_start + x2 * bytes_per_pixel
            head_pixels.extend(pixels[pixel_start:pixel_end])
        
        # 放大图像 (最近邻插值)
        if scale_factor > 1:
            scaled_pixels = []
            scaled_width = head_width * scale_factor
            scaled_height = head_height * scale_factor
            
            for y in range(scaled_height):
                orig_y = y // scale_factor
                for x in range(scaled_width):
                    orig_x = x // scale_factor
                    pixel_idx = (orig_y * head_width + orig_x) * bytes_per_pixel
                    scaled_pixels.extend(head_pixels[pixel_idx:pixel_idx + bytes_per_pixel])
            
            head_pixels = scaled_pixels
            head_width = scaled_width
            head_height = scaled_height
        
        # 设置默认输出路径
        if output_path is None:
            output_path = str(cache_directory('skins') / 'minecraft_head.png')
        
        # 写入PNG文件
        with open(output_path, 'wb') as f:
            writer = png.Writer(
                width=head_width,
                height=head_height,
                greyscale=False,
                alpha=(bytes_per_pixel == 4),
                bitdepth=8
            )
            writer.write_array(f, head_pixels)
        
        logger.info(f"成功提取头像: {head_width}x{head_height}, 保存至: {output_path}")
        return output_path
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise Exception(f"处理皮肤时发生错误: {str(e)}")
    finally:
        # 清理临时文件
        try:
            os.unlink(temp_path)
        except:
            pass


def process_skin_info(uuid, skin_info, output_dir=None, scale_factor=10):
    """
    处理皮肤信息字典，下载皮肤并提取头像
    
    Args:
        uuid (str): 玩家的UUID
        skin_info (dict): 包含皮肤信息的字典，必须包含'url'字段
        output_dir (str, optional): 输出目录
        scale_factor (int): 放大倍数
        
    Returns:
        str: 保存的头像文件路径
        
    Raises:
        ValueError: 如果皮肤信息字典中缺少'url'字段
    """
    # 从字典中提取URL
    skin_url = skin_info.get('url')
    if not skin_url:
        raise ValueError("皮肤信息字典中缺少'url'字段")
    
    # 创建输出目录
    if output_dir is None:
        output_dir = "."
    os.makedirs(output_dir, exist_ok=True)
    
    # 下载皮肤
    logger.info(f"正在下载皮肤: {skin_url}")
    skin_data = download_skin(skin_url)
    
    # 提取头部
    output_file = os.path.join(output_dir, f"{uuid}.png")
    return extract_minecraft_head(skin_data, output_file, scale_factor)


# 处理皮肤信息并获取头像
if __name__ == "__main__":
    # 示例皮肤信息
    skin_info = {
        'id': '3e0f41c9-e7df-4df1-95cf-60eab1a38443',
        'state': 'ACTIVE',
        'url': 'http://textures.minecraft.net/texture/7b738ad7ffa7132876f266c4c6e48ee4009f6c8fc4073d2b8c9e54e9e7562fe',
        'textureKey': '7b738ad7ffa7132876f266c4c6e48ee4009f6c8fc4073d2b8c9e54e9e7562fe',
        'variant': 'CLASSIC'
    }
    
    # 处理皮肤信息并保存头像
    output_path = process_skin_info(
        skin_info['id'],
        skin_info,
        output_dir=".",
        scale_factor=10
    )
    logger.info(f"头像已保存到: {output_path}")
