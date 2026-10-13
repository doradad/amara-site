$(document).ready(function () {
    // 仅在顶层计时：iframe / 嵌入页跳过，避免与外层并行上报双倍时长（同 _MaintenanceIcon isTop）
    var isTop = true;
    try { isTop = (window.top === window.self); } catch (e) { isTop = false; }
    if (!isTop) return;

    function checkDesignerCookie() {
        try {
            const isDesigner = $.cookie('IsDesigner');
            
            if (isDesigner) {
                const pairs = isDesigner.split('&');
                const designerData = pairs.reduce((acc, pair) => {
                    const [key, value] = pair.split('=');
                    acc[key] = value;
                    return acc;
                }, {});
                
                
                if (designerData && designerData.unionId) {
                    return designerData.unionId;
                }
            }
            return false;
        } catch (error) {
            console.log(error);
            return false;
        }
    }

    let designerUnionId = checkDesignerCookie();
    if (!designerUnionId) return;

    const maintenanceIcon = window.MaintenanceIcon || { show: function () {}, hide: function () {} };

    let timerInterval = null;
    let pollInterval = null;
    let seconds = 0;
    let isPageActive = false;

    // 活跃：!document.hidden && document.hasFocus()（同源 iframe 有焦点时顶帧一般为 true）
    // 每秒 evaluate；iframe→parent 脚本跳转偶致顶帧 hasFocus 卡住 → Designer/_MoveHover 内跳转前先 parent.focus()
    const POLL_MS = 1000;

    function sendRequest() {
        const data = {
            url: window.location.pathname,
            unionId: designerUnionId
        };
        $.ajax({
            type: 'post',
            url: '/admin/home/SaveMaintenanceData',
            data: data
        }).fail(function (error) {
            console.error('请求失败:', error);
        });
        seconds = 0;
    }

    function activatePage() {
        if (isPageActive) return;
        isPageActive = true;
        startTimer();
        maintenanceIcon.show();
    }

    function deactivatePage() {
        if (!isPageActive) return;
        isPageActive = false;
        stopTimer();
        saveTimerState();
        maintenanceIcon.hide();
    }

    function evaluate() {
        if (!document.hidden && document.hasFocus()) {
            activatePage();
        } else {
            deactivatePage();
        }
    }

    function startTimer() {
        if (timerInterval) {
            clearInterval(timerInterval);
            timerInterval = null;
        }

        try {
            const savedData = localStorage.getItem('crossPageTime');
            if (savedData) {
                const data = JSON.parse(savedData);
                seconds = data.seconds || 0;
                localStorage.removeItem('crossPageTime');

                if (seconds >= 60) {
                    sendRequest();
                }
            } else {
                seconds = 0;
            }
        } catch (e) {
            console.log('无法恢复跨页面时间');
            seconds = 0;
        }

        timerInterval = setInterval(function () {
            seconds++;
            if (seconds >= 60) {
                sendRequest();
            }
        }, 1000);
    }

    function stopTimer() {
        if (timerInterval) {
            clearInterval(timerInterval);
            timerInterval = null;
        }
    }

    function saveTimerState() {
        if (seconds > 0 && seconds < 60) {
            const saveData = {
                seconds: seconds,
                timestamp: Date.now()
            };
            localStorage.setItem('crossPageTime', JSON.stringify(saveData));
        }
    }

    document.addEventListener('visibilitychange', evaluate);
    pollInterval = setInterval(evaluate, POLL_MS);

    window.addEventListener('beforeunload', function () {
        if (pollInterval) {
            clearInterval(pollInterval);
            pollInterval = null;
        }
        deactivatePage();
    });

    evaluate();
});
