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
            currentTime: 0,
            duration: 0,
            isPlaying: false,
            chapters: []
        };
        
        this.init();
    }
    
    init() {
        // 从 localStorage 恢复状态
        this.loadState();
        
        // 绑定事件
        this.bindEvents();
        
        // 初始化 Media Session API
        this.initMediaSession();
        
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
        this.currentState.currentTime = 0;
        
        // 显示播放器和加载状态
        this.show();
        this.updateUI();
        this.playerLoading.classList.add('active');
        
        // 先暂停旧音频
        if (!this.audio.paused) {
            this.audio.pause();
        }
        
        // 设置新的音频源
        console.log(`切换到章节 ${chapterId}，URL: /stream/${chapterId}`);
        this.audio.src = `/stream/${chapterId}`;
        
        // 尝试播放
        this.play();
        
        // 保存状态
        this.saveState();
    }
    
    play() {
        return this.audio.play().then(() => {
            this.currentState.isPlaying = true;
            this.updatePlayPauseButton();
            this.playerLoading.classList.remove('active');
            this.saveState();
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

        this.pause();
        this.player.classList.remove('active');
        this.clearState();
    }
    
    updateUI() {
        this.playerChapter.textContent = this.currentState.chapterTitle || '未播放';
        this.playerNovel.textContent = this.currentState.novelTitle || '请选择章节';
    }
    
    updatePlayPauseButton() {
        this.btnPlayPause.textContent = this.audio.paused ? '▶' : '⏸';
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
        // 恢复播放位置
        if (this.currentState.currentTime > 0) {
            this.audio.currentTime = this.currentState.currentTime;
        }
    }
    
    onPlay() {
        this.currentState.isPlaying = true;
        this.updatePlayPauseButton();
        this.updateMediaSession();
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
        console.log('音频可以播放，缓冲完成');
    }
    
    onError(e) {
        console.error('音频加载错误:', e);
        this.playerLoading.classList.remove('active');
        
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
        localStorage.setItem('globalPlayerState', JSON.stringify(this.currentState));
    }
    
    loadState() {
        const saved = localStorage.getItem('globalPlayerState');
        if (saved) {
            try {
                this.currentState = JSON.parse(saved);
                
                // 恢复音频源
                if (this.currentState.chapterId) {
                    this.audio.src = `/stream/${this.currentState.chapterId}`;
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
}

// 初始化全局播放器
window.globalPlayer = new GlobalAudioPlayer();

// 暴露全局方法供页面调用
window.playAudiobook = function(novelId, novelTitle, chapterId, chapterTitle, chapters = []) {
    window.globalPlayer.playChapter(novelId, novelTitle, chapterId, chapterTitle, chapters);
};
