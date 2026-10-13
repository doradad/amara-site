$(document).ready(function () {
    let designerUnionId = checkDesignerCookie();
    // 检查 isDesigner cookie
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

    // 只有当 unionId 存在时才执行主代码
    if (designerUnionId) {
        let timerInterval = null;
        let pollInterval = null;
        let seconds = 0;
        let isPageActive = false;
        function sendRequest() { 
            const data = {
                url: window.location.pathname,
                unionId: designerUnionId
            };
            
            // const blob = new Blob([JSON.stringify(data)], {type: 'application/json'});
            // navigator.sendBeacon('/admin/home/SaveMaintenanceData', blob);
            $.ajax({
                type: 'post',
                url: '/admin/home/SaveMaintenanceData',
                data: data,
            }).fail(error => {
                console.error('请求失败:', error);
            });
            seconds = 0;
        }

        // 检查页面状态
        function checkPageState() {
            const isVisible = !document.hidden;
            const hasFocus = document.hasFocus();
            
            if (isVisible && hasFocus && !isPageActive) {
                activatePage();
            } else if ((!isVisible || !hasFocus) && isPageActive) {
                deactivatePage();
            }
        }

        // 激活页面
        function activatePage() {
            isPageActive = true;
            startTimer();
            startPolling();
        }

        // 停用页面
        function deactivatePage() {
            isPageActive = false;
            stopTimer();
            saveTimerState();
            // stopPolling();
        }

        function startPolling() {
            if (!document.hidden && !pollInterval) {
                pollInterval = setInterval(checkPageState, 1000);
            }
        }

        function stopPolling() {
            if (pollInterval) {
                clearInterval(pollInterval);
                pollInterval = null;
            }
        }

        function startTimer() {
            if (timerInterval) {
                clearInterval(timerInterval);
                timerInterval = null;
            };
            
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
            
            timerInterval = setInterval(() => {
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

        function handleVisibilityChange() {
            if (document.hidden) {
                stopPolling();
                deactivatePage();
            } else {
                startPolling();
            }
        }

        document.addEventListener('visibilitychange', handleVisibilityChange);

        window.addEventListener('beforeunload', function() {
            stopPolling();
            deactivatePage();
            document.removeEventListener('visibilitychange', handleVisibilityChange);
        });
        
        startPolling();
    }
});
