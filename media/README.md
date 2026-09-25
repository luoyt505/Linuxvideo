# media/ —— 示例媒体目录

把你要纳入 mediahub 媒体库的 **视频 / 音频 / 图片** 文件放进这个目录（或它的子目录），
然后在 Web 界面点击「扫描媒体库」，或执行：

```bash
./mediahub-cli scan --dir ./media
```

支持的扩展名：

- 视频：mp4 / mkv / avi / mov / flv / wmv / webm / m4v / mpg / mpeg / ts / m2ts / 3gp / rmvb / vob
- 音频：mp3 / flac / wav / aac / m4a / ogg / wma / opus / ape / alac / aiff
- 图片：jpg / jpeg / png / gif / bmp / webp / tiff / heic

也可以把 `.env` 中的 `MEDIA_DIRS` 指向服务器上的任意目录，例如：

```
MEDIA_DIRS=/srv/movies,/srv/music,/srv/photos
```

> 提示：mediahub **只读取**这些文件，不会重命名、移动或删除它们。
