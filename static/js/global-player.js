/**
 * NovelVoice 全局播放器
 * 支持跨页面持续播放、移动端后台播放、Media Session API
 */

class GlobalAudioPlayer {
    constructor() {
        // DOM 元素
        this.player = document.getElementById('globalPlayer');
        this.audio = document.getElementById('globalAudio');
        this.btnPlayPause = document.getElementById('btnPlayPause');
        this.btnPrev = document.getElementById('btnPrev');
        this.btnNext = document.getElementById('btnNext');
        this.btnClose = document.getElementById('btnClose');
        this.playerChapter = document.getElementById('playerChapter');
        this.playerNovel = document.getElementById('playerNovel');
        this.playerTime = document.getElementById('playerTime');
        this.playerProgress = document.getElementById('playerProgress');
        this.playerProgressBar = document.getElementById('playerProgressBar');
        this.playerLoading = document.getElementById('playerLoading');
        
        // 状态
        this.currentState = {
            novelId: null,
            novelTitle: '',
            chapterId: null,
            chapterTitle: '',
            offset: 0,
            currentTime: 0,
            duration: 0,
            isPlaying: false,
            chapters: []
        };
        
        // 【调试面板】用于在iPhone上显示调试信息
        this._initDebugPanel();
        
        this.init();
    }
    
    init() {
        // 从 localStorage 恢复状态
        this.loadState();
        
        // 绑定事件
        this.bindEvents();
        
        // 初始化 Media Session API
        this.initMediaSession();
        
        // 监听页面可见性变化（iOS Safari 切换页面时的关键）
        this.handleVisibilityChange();
        
        // 如果有保存的播放状态，恢复播放
        if (this.currentState.chapterId) {
            this.show();
            this.updateUI();
            
            // 尝试恢复播放（可能被自动播放策略阻止）
            if (this.currentState.isPlaying) {
                this.play().catch(err => {
                    console.log('自动播放被阻止，等待用户交互');
                });
            }
        }
        
        // 定期保存状态
        setInterval(() => this.saveState(), 2000);
    }
    
    bindEvents() {
        // 播放/暂停
        this.btnPlayPause.addEventListener('click', () => {
            if (this.audio.paused) {
                // 【关键修复】点击播放前，检查是否需要恢复位置
                // 优先使用 _pendingSeekTime，其次使用 currentState.currentTime
                const pendingTime = this._pendingSeekTime || 0;
                const savedTime = this.currentState.currentTime || 0;
                const targetTime = pendingTime > 0 ? pendingTime : savedTime;
                const currentAudioTime = this.audio.currentTime || 0;
                
                this._log(`点击播放: target=${targetTime.toFixed(1)}s, audio=${currentAudioTime.toFixed(1)}s`);
                
                // 如果目标位置与当前音频位置相差超过2秒，或者当前位置为0，需要恢复
                if (targetTime > 0 && (currentAudioTime === 0 || Math.abs(currentAudioTime - targetTime) > 2)) {
                    this._log(`恢复位置: ${currentAudioTime.toFixed(1)}s → ${targetTime.toFixed(1)}s`);
                    
                    // 如果音频已加载完成，直接设置 currentTime
                    if (this.audio.readyState >= 1) {
                        this.audio.currentTime = targetTime;
                        this._pendingSeekTime = 0;
                    } else {
                        // 音频还未加载，等待 loadedmetadata 后恢复
                        this._pendingSeekTime = targetTime;
                        console.log(`[播放按钮] 音频未加载完成，设置待恢复位置: ${targetTime}秒`);
                    }
                }
                
                this.play();
            } else {
                this.pause();
            }
        });
        
        // 上一章
        this.btnPrev.addEventListener('click', () => this.playPrevChapter());
        
        // 下一章
        this.btnNext.addEventListener('click', () => this.playNextChapter());
        
        // 关闭播放器
        this.btnClose.addEventListener('click', () => this.close());
        
        // 进度条点击
        this.playerProgress.addEventListener('click', (e) => {
            const rect = this.playerProgress.getBoundingClientRect();
            const percent = (e.clientX - rect.left) / rect.width;
            this.audio.currentTime = this.audio.duration * percent;
        });
        
        // Audio 事件
        this.audio.addEventListener('timeupdate', () => this.onTimeUpdate());
        this.audio.addEventListener('loadedmetadata', () => this.onLoadedMetadata());
        this.audio.addEventListener('play', () => this.onPlay());
        this.audio.addEventListener('playing', () => this.onPlaying());
        this.audio.addEventListener('pause', () => this.onPause());
        this.audio.addEventListener('ended', () => this.onEnded());
        this.audio.addEventListener('waiting', () => this.onWaiting());
        this.audio.addEventListener('canplay', () => this.onCanPlay());
        this.audio.addEventListener('error', (e) => this.onError(e));
    }
    
    // 播放指定章节
    playChapter(novelId, novelTitle, chapterId, chapterTitle, chapters = []) {
        console.log(`[GlobalPlayer] playChapter 被调用`);
        console.log(`  当前章节ID: ${this.currentState.chapterId}`);
        console.log(`  请求章节ID: ${chapterId}`);
        console.log(`  ID类型: 当前=${typeof this.currentState.chapterId}, 请求=${typeof chapterId}`);
        
        // 清除关闭标志（开始新的播放）
        this._isClosed = false;
        
        // 关键优化：如果是同一章节，不重新设置 src
        if (this.currentState.chapterId == chapterId) {
            console.log('✅ 已经在播放该章节，继续播放（不重新加载）');
            
            // 只更新 UI 和显示播放器
            this.show();
            this.updateUI();
            
            // 如果暂停了就播放
            if (this.audio.paused) {
                console.log('音频已暂停，恢复播放');
                this.play();
            } else {
                console.log('音频正在播放，保持状态');
            }
            
            return;
        }
        
        console.log('⚠️ 检测到章节切换，需要重新加载音频');
        
        // 保存旧的章节 ID（用于判断是否需要中止旧请求）
        const oldChapterId = this.currentState.chapterId;
        
        // 更新状态
        this.currentState.novelId = novelId;
        this.currentState.novelTitle = novelTitle;
        this.currentState.chapterId = chapterId;
        this.currentState.chapterTitle = chapterTitle;
        this.currentState.chapters = chapters;
        this.currentState.offset = 0;
        this.currentState.currentTime = 0;
        
        // 显示播放器和加载状态
        this.show();
        this.updateUI();
        this.playerLoading.classList.add('active');
        
        // 先暂停旧音频
        if (!this.audio.paused) {
            this.audio.pause();
        }
        
        // 检测是否支持HLS
        const useHLS = this._shouldUseHLS();
        
        if (useHLS) {
            // 使用HLS
            const hlsUrl = `/hls/${chapterId}/playlist.m3u8`;
            console.log(`切换到章节 ${chapterId}，使用HLS: ${hlsUrl}`);
            this._loadHLS(hlsUrl);
        } else {
            // 使用传统流式播放
            const streamUrl = `/stream/${chapterId}`;
            console.log(`切换到章节 ${chapterId}，使用传统流: ${streamUrl}`);
            this.audio.src = streamUrl;
        }
        
        // 尝试播放
        this.play();
        
        // 保存状态
        this.saveState();
    }
    
    // 检测是否应该使用HLS
    _shouldUseHLS() {
        // iOS设备优先使用HLS
        const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
        if (isIOS) {
            console.log('[播放器] 检测到iOS设备，使用HLS');
            return true;
        }
        
        // 其他设备：检查是否支持HLS.js或原生HLS
        if (window.Hls && window.Hls.isSupported()) {
            console.log('[播放器] 支持HLS.js，使用HLS');
            return true;
        }
        
        if (this.audio.canPlayType('application/vnd.apple.mpegurl')) {
            console.log('[播放器] 原生支持HLS，使用HLS');
            return true;
        }
        
        console.log('[播放器] 不支持HLS，使用传统流');
        return false;
    }
    
    // 加载HLS流
    _loadHLS(url) {
        // iOS Safari原生支持HLS
        if (this.audio.canPlayType('application/vnd.apple.mpegurl')) {
            console.log('[HLS] 使用原生HLS支持');
            this.audio.src = url;
            return;
        }
        
        // 使用HLS.js (其他浏览器)
        if (window.Hls && window.Hls.isSupported()) {
            console.log('[HLS] 使用HLS.js');
            
            // 销毁旧的HLS实例
            if (this._hls) {
                this._hls.destroy();
            }
            
            // 创建新的HLS实例
            this._hls = new Hls({
                debug: false,
                enableWorker: true,
                lowLatencyMode: true,
            });
            
            this._hls.loadSource(url);
            this._hls.attachMedia(this.audio);
            
            this._hls.on(Hls.Events.MANIFEST_PARSED, () => {
                console.log('[HLS.js] Manifest已解析');
            });
            
            // 重试计数器
            this._hlsRetryCount = 0;
            const MAX_RETRIES = 3;
            
            this._hls.on(Hls.Events.ERROR, (event, data) => {
                console.error('[HLS.js] 错误:', data);
                
                if (data.fatal) {
                    switch(data.type) {
                        case Hls.ErrorTypes.NETWORK_ERROR:
                            // 检查是否是404错误（manifest加载失败）
                            if (data.details === 'manifestLoadError' || data.response?.code === 404) {
                                console.error('[HLS.js] HLS文件不存在(404)，停止加载');
                                this._hls.destroy();
                                this._hls = null;
                                
                                // 降级到传统流
                                console.log('[HLS.js] 降级到传统流');
                                this.audio.src = `/stream/${this.currentState.chapterId}`;
                                break;
                            }
                            
                            // 其他网络错误，有限次重试
                            this._hlsRetryCount++;
                            if (this._hlsRetryCount < MAX_RETRIES) {
                                console.error(`[HLS.js] 网络错误，尝试恢复... (${this._hlsRetryCount}/${MAX_RETRIES})`);
                                this._hls.startLoad();
                            } else {
                                console.error('[HLS.js] 重试次数已达上限，销毁实例');
                                this._hls.destroy();
                                this._hls = null;
                                alert('音频加载失败，请稍后重试');
                            }
                            break;
                            
                        case Hls.ErrorTypes.MEDIA_ERROR:
                            console.error('[HLS.js] 媒体错误，尝试恢复...');
                            this._hls.recoverMediaError();
                            break;
                            
                        default:
                            console.error('[HLS.js] 致命错误，销毁实例');
                            this._hls.destroy();
                            this._hls = null;
                            break;
                    }
                }
            });
            
            // 成功加载后重置重试计数
            this._hls.on(Hls.Events.MANIFEST_LOADED, () => {
                this._hlsRetryCount = 0;
            });
            
            return;
        }
        
        // 降级到传统流
        console.warn('[HLS] 不支持HLS，降级到传统流');
        this.audio.src = `/stream/${this.currentState.chapterId}`;
    }
    
    play() {
        // 【关键修复】在调用play之前，保存期望的播放位置
        const expectedTime = this.audio.currentTime || this.currentState.currentTime || this._pendingSeekTime || 0;
        this._log(`play(): 期望位置=${expectedTime.toFixed(1)}s`);
        
        // 设置期望位置，供 playing 事件使用
        this._expectedPlayTime = expectedTime;
        
        return this.audio.play().then(() => {
            this.currentState.isPlaying = true;
            this.updatePlayPauseButton();
            this.playerLoading.classList.remove('active');
            this.saveState();
            
            // 【关键修复】播放成功后，检查位置是否被重置
            setTimeout(() => {
                if (expectedTime > 2 && this.audio.currentTime < 2) {
                    this._log(`play()后位置被重置，恢复到: ${expectedTime.toFixed(1)}s`);
                    this.audio.currentTime = expectedTime;
                }
            }, 100);
        }).catch(err => {
            console.error('播放失败:', err);
            this.playerLoading.classList.remove('active');
            
            // 如果是网络错误，提示用户
            if (err.name === 'NotSupportedError' || err.name === 'AbortError') {
                alert('音频加载失败，请检查网络连接或稍后重试');
            }
        });
    }
    
    pause() {
        this.audio.pause();
        this.currentState.isPlaying = false;
        this.updatePlayPauseButton();
        this.saveState();
    }
    
    playPrevChapter() {
        if (!this.currentState.chapters.length) return;
        
        const currentIndex = this.currentState.chapters.findIndex(
            ch => ch.id == this.currentState.chapterId
        );
        
        if (currentIndex > 0) {
            const prevChapter = this.currentState.chapters[currentIndex - 1];
            this.playChapter(
                this.currentState.novelId,
                this.currentState.novelTitle,
                prevChapter.id,
                prevChapter.title,
                this.currentState.chapters
            );
        } else {
            alert('已经是第一章了');
        }
    }
    
    playNextChapter() {
        if (!this.currentState.chapters.length) return;
        
        const currentIndex = this.currentState.chapters.findIndex(
            ch => ch.id == this.currentState.chapterId
        );
        
        if (currentIndex < this.currentState.chapters.length - 1) {
            const nextChapter = this.currentState.chapters[currentIndex + 1];
            this.playChapter(
                this.currentState.novelId,
                this.currentState.novelTitle,
                nextChapter.id,
                nextChapter.title,
                this.currentState.chapters
            );
        } else {
            alert('已经是最后一章了');
        }
    }
    
    show() {
        this.player.classList.add('active');
    }
    
    close() {
        // 停止当前章节的后台生成任务（与暂停区分开）
        if (this.currentState.chapterId) {
            fetch(`/cancel-generation/${this.currentState.chapterId}`, {
                method: 'POST'
            }).catch(err => {
                console.error('取消后台章节生成任务失败', err);
            });
        }

        // 标记为主动关闭状态，阻止错误重连
        this._isClosed = true;

        this.pause();
        
        // 销毁HLS实例，停止所有加载
        if (this._hls) {
            console.log('[HLS.js] 销毁HLS实例');
            this._hls.destroy();
            this._hls = null;
        }
        
        // 清空音频源，停止加载
        this.audio.src = '';
        this.audio.load();
        
        // 清理所有待恢复的位置标记
        this._pendingSeekTime = 0;
        this._expectedPlayTime = 0;
        
        this.player.classList.remove('active');
        
        // 清理状态（包括localStorage）
        this.clearState();
    }
    
    updateUI() {
        this.playerChapter.textContent = this.currentState.chapterTitle || '未播放';
        this.playerNovel.textContent = this.currentState.novelTitle || '请选择章节';
    }
    
    updatePlayPauseButton() {
        this.btnPlayPause.textContent = this.audio.paused ? '▶' : '■';
    }
    
    updateProgress() {
        if (this.audio.duration) {
            const percent = (this.audio.currentTime / this.audio.duration) * 100;
            this.playerProgressBar.style.width = percent + '%';
        }
    }
    
    updateTime() {
        const current = this.formatTime(this.audio.currentTime);
        const duration = this.formatTime(this.audio.duration);
        this.playerTime.textContent = `${current} / ${duration}`;
    }
    
    formatTime(seconds) {
        if (!seconds || isNaN(seconds)) return '0:00';
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }
    
    // Audio 事件处理
    onTimeUpdate() {
        this.currentState.currentTime = this.audio.currentTime;
        this.currentState.duration = this.audio.duration;
        this.updateProgress();
        this.updateTime();
    }
    
    onLoadedMetadata() {
        this.updateTime();
        
        // 【关键修复】恢复播放位置
        // 优先使用 _pendingSeekTime（页面加载时设置的待恢复位置）
        const pendingTime = this._pendingSeekTime || 0;
        const savedTime = this.currentState.currentTime || 0;
        const targetTime = pendingTime > 0 ? pendingTime : savedTime;
        
        if (targetTime > 0 && this.audio.currentTime === 0) {
            this._log(`metadata恢复: ${targetTime.toFixed(1)}s`);
            this.audio.currentTime = targetTime;
            // 清除待恢复标记
            this._pendingSeekTime = 0;
        }
    }
    
    onPlay() {
        this.currentState.isPlaying = true;
        this.updatePlayPauseButton();
        this.updateMediaSession();
    }
    
    // 【关键修复】音频真正开始播放时触发
    onPlaying() {
        const expectedTime = this._expectedPlayTime || 0;
        const currentTime = this.audio.currentTime || 0;
        
        // 如果期望位置超过2秒，但当前位置小于2秒，说明位置被重置了
        if (expectedTime > 2 && currentTime < 2) {
            this._log(`playing事件检测到位置重置: ${currentTime.toFixed(1)}s → ${expectedTime.toFixed(1)}s`);
            this.audio.currentTime = expectedTime;
        }
        
        // 清除期望位置标记
        this._expectedPlayTime = 0;
    }
    
    onPause() {
        this.currentState.isPlaying = false;
        this.updatePlayPauseButton();
    }
    
    onEnded() {
        // 自动播放下一章
        this.playNextChapter();
    }
    
    onWaiting() {
        this.playerLoading.classList.add('active');
    }
    
    onCanPlay() {
        this.playerLoading.classList.remove('active');
        
        // 【双重保障】如果还有待恢复的位置，在这里恢复
        const pendingTime = this._pendingSeekTime || 0;
        if (pendingTime > 0 && this.audio.currentTime < pendingTime - 2) {
            this._log(`canPlay恢复: ${pendingTime.toFixed(1)}s`);
            this.audio.currentTime = pendingTime;
            this._pendingSeekTime = 0;
        }
        
        this._log('音频就绪');
    }
    
    onError(e) {
        console.error('音频加载错误:', e);
        this.playerLoading.classList.remove('active');
        
        // 如果是用户主动关闭播放器，不进行重连
        if (this._isClosed) {
            console.log('播放器已关闭，跳过重连');
            return;
        }
        
        // 尝试重连
        setTimeout(() => {
            console.log('尝试重新加载...');
            this.audio.load();
        }, 3000);
    }
    
    // Media Session API（移动端锁屏控制）
    initMediaSession() {
        if ('mediaSession' in navigator) {
            navigator.mediaSession.setActionHandler('play', () => this.play());
            navigator.mediaSession.setActionHandler('pause', () => this.pause());
            navigator.mediaSession.setActionHandler('previoustrack', () => this.playPrevChapter());
            navigator.mediaSession.setActionHandler('nexttrack', () => this.playNextChapter());
        }
    }
    
    updateMediaSession() {
        if ('mediaSession' in navigator) {
            navigator.mediaSession.metadata = new MediaMetadata({
                title: this.currentState.chapterTitle,
                artist: this.currentState.novelTitle,
                album: 'NovelVoice 有声书',
                artwork: [
                    { src: '/static/icon-96.png', sizes: '96x96', type: 'image/png' },
                    { src: '/static/icon-512.png', sizes: '512x512', type: 'image/png' }
                ]
            });
        }
    }
    
    // 状态持久化
    saveState() {
        // 确保 currentTime 是最新的
        if (this.audio && !isNaN(this.audio.currentTime) && this.audio.currentTime > 0) {
            this.currentState.currentTime = this.audio.currentTime;
        }
        localStorage.setItem('globalPlayerState', JSON.stringify(this.currentState));
    }
    
    // 同步保存状态（用于页面卸载时，确保数据写入）
    saveStateSync() {
        // 确保 currentTime 是最新的
        if (this.audio && !isNaN(this.audio.currentTime) && this.audio.currentTime > 0) {
            this.currentState.currentTime = this.audio.currentTime;
        }
        const stateJson = JSON.stringify(this.currentState);
        localStorage.setItem('globalPlayerState', stateJson);
        this._log(`保存状态: time=${this.currentState.currentTime?.toFixed(1)}s`);
    }
    
    async loadState() {
        const saved = localStorage.getItem('globalPlayerState');
        if (saved) {
            try {
                this.currentState = JSON.parse(saved);
                this._log(`加载状态: chId=${this.currentState.chapterId}, time=${this.currentState.currentTime?.toFixed(1)}s`);
                
                // 恢复音频源
                if (this.currentState.chapterId) {
                    // 标记需要恢复的播放位置
                    this._pendingSeekTime = this.currentState.currentTime || 0;
                    this._log(`设置待恢复位置: ${this._pendingSeekTime.toFixed(1)}s`);
                    
                    // 检测是否使用HLS
                    const useHLS = this._shouldUseHLS();
                    
                    if (useHLS) {
                        // 尝试使用HLS播放，URL中添加保存的时间
                        this.currentState.offset += this.currentState.currentTime || 0;
                        const hlsUrl = `/hls/${this.currentState.chapterId}/playlist.m3u8?ts=${this.currentState.offset}`;
                        this._log(`恢复播放: 使用HLS ${hlsUrl}`);

                        // 首先清除HLS缓存，缓存清除完成后再尝试使用HLS播放
                        fetch(`/hls/${this.currentState.chapterId}/clear`)
                        .then(() => {
                            // fetch成功：直接加载HLS
                            this._loadHLS(hlsUrl);
                        })
                        .catch(err => {
                            console.error('清除HLS缓存失败:', err);
                        });
                        
                    } else {
                        const streamUrl = `/stream/${this.currentState.chapterId}`;
                        this._log(`恢复播放: 使用传统流 ${streamUrl}`);
                        this.audio.src = streamUrl;
                    }
                }
            } catch (e) {
                console.error('加载状态失败:', e);
            }
        }
    }
    
    clearState() {
        this.currentState = {
            novelId: null,
            novelTitle: '',
            chapterId: null,
            chapterTitle: '',
            currentTime: 0,
            duration: 0,
            isPlaying: false,
            chapters: []
        };
        localStorage.removeItem('globalPlayerState');
    }
    
    // 监听页面可见性变化（iOS Safari 切换页面/应用的关键）
    handleVisibilityChange() {
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                // 页面被隐藏（切换到其他页面/应用）
                console.log('[iOS优化] 页面被隐藏，保存当前状态（音频继续播放）');
                this.saveState();
                // 注意：不主动暂停音频，让其继续在后台播放
            } else {
                // 页面变为可见（从其他页面/应用切换回来）
                // console.log('[iOS优化] 页面恢复可见，检查播放状态');
                // this.handlePageRestored();
            }
        });
        
        // iOS Safari 特定事件
        window.addEventListener('pageshow', (event) => {
            if (event.persisted) {
                // 从 bfcache 恢复
                console.log('[iOS优化] 从 bfcache 恢复，检查播放状态');
                this.handlePageRestored();
            }
        });
        
        // 【关键修复】监听页面卸载事件，确保站内跳转时保存播放状态
        window.addEventListener('beforeunload', () => {
            console.log('[站内跳转] beforeunload 触发，保存播放状态');
            this.saveStateSync();
        });
        
        window.addEventListener('pagehide', () => {
            console.log('[站内跳转] pagehide 触发，保存播放状态');
            this.saveStateSync();
        });
    }
    
    // 页面恢复时的处理逻辑
    handlePageRestored() {
        // 重新加载状态
        this.loadState();
        
        // 如果有正在播放的章节
        if (this.currentState.chapterId) {
            const hadAudioSrc = this.audio.src && this.audio.src.includes(`/stream/${this.currentState.chapterId}`);
            const savedTime = this.currentState.currentTime || 0;
            const wasPlaying = this.currentState.isPlaying;
            
            console.log(`[iOS优化] 页面恢复，章节ID=${this.currentState.chapterId}, 保存位置=${savedTime}秒, 之前播放状态=${wasPlaying}`);
            
            // 检查 audio.src 是否被清空（iOS Safari 某些情况下会清空）
            if (!hadAudioSrc) {
                console.log('[iOS优化] 音频源被清空，重新设置');
                this.audio.src = `/stream/${this.currentState.chapterId}`;
                
                // 等待 loadedmetadata 事件后，恢复播放位置
                const restorePlayback = () => {
                    if (savedTime > 0) {
                        console.log(`[iOS优化] loadedmetadata触发，恢复播放位置到: ${savedTime}秒`);
                        this.audio.currentTime = savedTime;
                    }
                    
                    // 如果之前在播放，自动恢复播放
                    if (wasPlaying) {
                        console.log('[iOS优化] 尝试自动恢复播放');
                        this.play().catch(err => {
                            console.log('[iOS优化] 自动恢复播放失败，需要用户手动点击:', err);
                            // 标记为暂停状态
                            this.currentState.isPlaying = false;
                            this.updatePlayPauseButton();
                        });
                    }
                };
                this.audio.addEventListener('loadedmetadata', restorePlayback, { once: true });
            } else {
                // audio.src 还在，检查播放位置和状态
                console.log(`[iOS优化] 音频源存在，当前audio.currentTime=${this.audio.currentTime}秒, audio.paused=${this.audio.paused}`);
                
                // 关键修复：iOS Safari页面切换后，audio.currentTime可能被重置为0
                // 如果检测到位置被重置（当前为0但保存的不是0），立即恢复
                if (savedTime > 0 && this.audio.currentTime === 0) {
                    console.log(`[iOS优化] 检测到播放位置被重置，立即恢复到: ${savedTime}秒`);
                    this.audio.currentTime = savedTime;
                } else if (savedTime > 0 && Math.abs(this.audio.currentTime - savedTime) > 2) {
                    console.log(`[iOS优化] 播放位置偏差较大(${this.audio.currentTime}秒 vs ${savedTime}秒)，校正`);
                    this.audio.currentTime = savedTime;
                }
                
                // 处理播放状态
                if (this.audio.paused) {
                    console.log('[iOS优化] 音频当前已暂停');
                    
                    // 关键修复：确保播放位置正确
                    if (savedTime > 0 && this.audio.currentTime !== savedTime) {
                        console.log(`[站内切换修复] 音频暂停时恢复位置: ${this.audio.currentTime}秒 → ${savedTime}秒`);
                        this.audio.currentTime = savedTime;
                    }
                    
                    // 更新UI为暂停状态
                    this.currentState.isPlaying = false;
                    this.updatePlayPauseButton();
                    
                    // 如果之前在播放，尝试恢复（但不自动播放，等待用户点击）
                    if (wasPlaying) {
                        console.log('[iOS优化] 之前在播放，但现在已暂停，等待用户手动点击播放按钮');
                        // 不自动调用play()，让用户手动点击，避免autoplay policy阻止
                    }
                } else {
                    // 音频正在播放，确保状态同步
                    console.log('[iOS优化] 音频正在播放，同步状态');
                    this.currentState.isPlaying = true;
                    this.updatePlayPauseButton();
                }
            }
        }
    }
    
    // 【调试面板】初始化
    _initDebugPanel() {
        // 创建调试面板
        const panel = document.createElement('div');
        panel.id = 'audioDebugPanel';
        panel.innerHTML = `
            <div style="
                position: fixed;
                top: 10px;
                left: 10px;
                right: 10px;
                background: rgba(0,0,0,0.85);
                color: #0f0;
                font-size: 11px;
                font-family: monospace;
                padding: 10px;
                border-radius: 8px;
                z-index: 99999;
                max-height: 200px;
                overflow-y: auto;
                display: none;
            ">
                <div style="display:flex;justify-content:space-between;margin-bottom:8px;">
                    <b>🔧 播放器调试</b>
                    <span id="debugClose" style="cursor:pointer;">✕</span>
                </div>
                <div id="debugStatus" style="margin-bottom:5px;"></div>
                <div id="debugLog" style="max-height:120px;overflow-y:auto;"></div>
            </div>
        `;
        document.body.appendChild(panel);
        
        this._debugPanel = panel.firstElementChild;
        this._debugStatus = document.getElementById('debugStatus');
        this._debugLogEl = document.getElementById('debugLog');
        
        // 关闭按钮
        document.getElementById('debugClose').addEventListener('click', () => {
            this._debugPanel.style.display = 'none';
        });
    }
    
    // 【调试面板】打开调试面板（供外部调用）
    showDebugPanel() {
        if (this._debugPanel) {
            this._debugPanel.style.display = 'block';
            this._updateDebugStatus();
        }
    }
    
    // 【调试面板】更新状态显示
    _updateDebugStatus() {
        if (!this._debugStatus) return;
        const audioTime = this.audio ? this.audio.currentTime : 0;
        const savedTime = this.currentState.currentTime || 0;
        const pendingTime = this._pendingSeekTime || 0;
        const readyState = this.audio ? this.audio.readyState : -1;
        
        this._debugStatus.innerHTML = `
            <div>📍 audio.currentTime: <b>${audioTime.toFixed(1)}秒</b></div>
            <div>💾 savedTime: <b>${savedTime.toFixed(1)}秒</b></div>
            <div>⏳ pendingSeekTime: <b>${pendingTime.toFixed(1)}秒</b></div>
            <div>🎵 readyState: ${readyState} | paused: ${this.audio?.paused}</div>
            <div>📖 chapterId: ${this.currentState.chapterId}</div>
        `;
    }
    
    // 【调试面板】添加日志
    _log(msg) {
        console.log('[Player] ' + msg);
        if (!this._debugLogEl) return;
        try {
            const time = new Date().toLocaleTimeString();
            const div = document.createElement('div');
            div.style.borderBottom = '1px solid #333';
            div.style.padding = '2px 0';
            div.textContent = `[${time}] ${msg}`;
            this._debugLogEl.insertBefore(div, this._debugLogEl.firstChild);
            // 只保留最近20条
            while (this._debugLogEl.children.length > 20) {
                this._debugLogEl.removeChild(this._debugLogEl.lastChild);
            }
            this._updateDebugStatus();
        } catch(e) {}
    }
}

// 初始化全局播放器
window.globalPlayer = new GlobalAudioPlayer();

// 暂露全局方法供页面调用
window.playAudiobook = function(novelId, novelTitle, chapterId, chapterTitle, chapters = []) {
    window.globalPlayer.playChapter(novelId, novelTitle, chapterId, chapterTitle, chapters);
};

// 暗号：URL加 ?debug=1 打开调试面板
if (window.location.search.includes('debug=1')) {
    setTimeout(() => window.globalPlayer.showDebugPanel(), 500);
}
