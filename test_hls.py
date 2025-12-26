#!/usr/bin/env python3
"""
HLS功能测试脚本
用于验证HLS转换和播放功能
"""
import os
import sys

# 添加app目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from hls_manager import get_hls_manager


def test_hls_conversion():
    """测试HLS转换功能"""
    print("\n" + "="*60)
    print("HLS功能测试")
    print("="*60 + "\n")
    
    # 初始化HLS管理器
    hls_manager = get_hls_manager('hls_cache')
    print(f"✓ HLS管理器初始化完成")
    print(f"  缓存目录: {hls_manager.hls_base_dir}\n")
    
    # 检查是否有测试MP3文件
    test_mp3 = 'audio/chapter_1.mp3'
    
    if not os.path.exists(test_mp3):
        print(f"⚠️  警告: 测试MP3文件不存在: {test_mp3}")
        print("   请先生成至少一个章节的音频文件")
        print("\n建议:")
        print("   1. 启动应用: python3 app/app.py")
        print("   2. 上传一本小说")
        print("   3. 播放第一章,等待音频生成")
        print("   4. 再次运行本测试脚本\n")
        return False
    
    print(f"✓ 找到测试文件: {test_mp3}")
    file_size = os.path.getsize(test_mp3)
    print(f"  文件大小: {file_size / 1024 / 1024:.2f} MB\n")
    
    # 测试转换
    chapter_id = 1
    print(f"开始转换章节 {chapter_id} 为HLS格式...")
    
    result = hls_manager.convert_mp3_to_hls(chapter_id, test_mp3)
    
    if result:
        print(f"\n✅ 转换成功!")
        print(f"   Playlist: {result}")
        
        # 检查状态
        status = hls_manager.get_hls_status(chapter_id)
        print(f"\n转换状态:")
        print(f"   完成: {status['ready']}")
        print(f"   分段数: {status['segments']}")
        print(f"   总时长: {status['duration']:.1f}秒")
        
        # 显示生成的文件
        hls_dir = hls_manager.get_hls_dir(chapter_id)
        if os.path.exists(hls_dir):
            files = os.listdir(hls_dir)
            print(f"\n生成的文件 (共{len(files)}个):")
            for f in sorted(files):
                file_path = os.path.join(hls_dir, f)
                size = os.path.getsize(file_path)
                print(f"   - {f} ({size / 1024:.1f} KB)")
        
        # 显示playlist内容
        print(f"\nPlaylist内容预览:")
        print("-" * 60)
        with open(result, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            for i, line in enumerate(lines[:20]):  # 只显示前20行
                print(f"   {line.rstrip()}")
            if len(lines) > 20:
                print(f"   ... (省略{len(lines) - 20}行)")
        print("-" * 60)
        
        print(f"\n📱 测试播放:")
        print(f"   在浏览器中访问: http://localhost:5002/hls/{chapter_id}/playlist.m3u8")
        print(f"   或在iOS设备上直接播放此URL\n")
        
        return True
    else:
        print(f"\n❌ 转换失败")
        return False


def test_check_ffmpeg():
    """检查FFmpeg是否可用"""
    print("\n检查FFmpeg...")
    import subprocess
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True,
            text=True,
            check=True
        )
        version_line = result.stdout.split('\n')[0]
        print(f"✓ FFmpeg已安装: {version_line}")
        return True
    except FileNotFoundError:
        print("❌ FFmpeg未安装")
        print("\n安装方法:")
        print("  Ubuntu/Debian: sudo apt-get install ffmpeg")
        print("  macOS: brew install ffmpeg")
        print("  其他: 参考 https://ffmpeg.org/download.html\n")
        return False
    except Exception as e:
        print(f"❌ 检查FFmpeg时出错: {e}")
        return False


if __name__ == '__main__':
    # 检查FFmpeg
    if not test_check_ffmpeg():
        print("\n⚠️  请先安装FFmpeg后再运行此测试")
        sys.exit(1)
    
    # 测试HLS转换
    success = test_hls_conversion()
    
    if success:
        print("\n" + "="*60)
        print("✅ HLS功能测试通过!")
        print("="*60 + "\n")
        sys.exit(0)
    else:
        print("\n" + "="*60)
        print("❌ HLS功能测试失败")
        print("="*60 + "\n")
        sys.exit(1)
