/**
 * 检测 Android 应用中是否使用了 OkHttp、TTNet、HttpURLConnection。
 * 说明：
 * 1. OkHttp / TTNet 通过类存在性与可选 Hook 做快速摸底。
 * 2. HttpURLConnection 属于系统类，不能仅凭 Java.use 判断“应用一定在用”，
 *    这里改为 Hook URL.openConnection()，只在运行时真的触发时再输出。
 */
Java.perform(function () {
    const observeDurationMs = 30000;
    const seenHttpUrlTargets = {};

    function logInfo(message) {
        console.log("[*] " + message);
    }

    function logHit(message) {
        console.log("[+] " + message);
    }

    function logWarn(message) {
        console.log("[!] " + message);
    }

    function logMiss(message) {
        console.log("[-] " + message);
    }

    function markHttpUrlTarget(url) {
        if (seenHttpUrlTargets[url]) {
            return false;
        }
        seenHttpUrlTargets[url] = true;
        return true;
    }

    function checkOkHttp() {
        try {
            Java.use("okhttp3.OkHttpClient");
            logHit("检测到应用包含 OkHttp：okhttp3.OkHttpClient");

            try {
                const OkHttp = Java.use("okhttp3.OkHttp");
                const version = OkHttp.VERSION.value;
                logHit("OkHttp 版本：" + version + "（来源：okhttp3.OkHttp.VERSION）");
                return;
            } catch (_error) {
                logWarn("未从 okhttp3.OkHttp.VERSION 读取到版本，继续尝试 OkHttp 3 方式。");
            }

            try {
                const Version = Java.use("okhttp3.internal.Version");
                const userAgent = Version.userAgent();
                logHit("OkHttp 版本：" + userAgent + "（来源：okhttp3.internal.Version）");
            } catch (_error) {
                logWarn("未能从 okhttp3.internal.Version 读取 OkHttp 版本。");
            }
        } catch (_error) {
            logMiss("未检测到 OkHttp。");
        }
    }

    function checkTTNet() {
        try {
            Java.use("com.bytedance.ttnet.TTNetInit");
            logHit("检测到应用包含 TTNet：com.bytedance.ttnet.TTNetInit");
        } catch (_error) {
            logMiss("未检测到 TTNet。");
            return;
        }

        try {
            const RetrofitMetrics = Java.use("com.bytedance.retrofit2.RetrofitMetrics");
            const getRetrofitLog = RetrofitMetrics.getRetrofitLog.overload();
            getRetrofitLog.implementation = function () {
                const result = getRetrofitLog.call(this);
                logHit("捕获到 TTNet RetrofitMetrics.getRetrofitLog() 调用：");
                console.log(result);
                return result;
            };
            logInfo("已 Hook TTNet 的 RetrofitMetrics.getRetrofitLog()，后续若命中会输出日志内容。");
        } catch (_error) {
            logWarn("检测到 TTNet，但未能 Hook RetrofitMetrics.getRetrofitLog()。");
        }
    }

    function checkHttpURLConnection() {
        try {
            const URL = Java.use("java.net.URL");
            const openConnectionNoArgs = URL.openConnection.overload();
            const openConnectionWithProxy = URL.openConnection.overload("java.net.Proxy");

            openConnectionNoArgs.implementation = function () {
                const result = openConnectionNoArgs.call(this);
                const target = this.toString();
                if (markHttpUrlTarget(target)) {
                    logHit("捕获到 HttpURLConnection/URLConnection 请求目标：" + target);
                }
                return result;
            };

            openConnectionWithProxy.implementation = function (proxy) {
                const result = openConnectionWithProxy.call(this, proxy);
                const target = this.toString();
                if (markHttpUrlTarget(target)) {
                    logHit("捕获到经代理打开的 HttpURLConnection/URLConnection 请求目标：" + target);
                }
                return result;
            };

            logInfo("已 Hook java.net.URL.openConnection()，后续若应用实际使用 HttpURLConnection 会输出目标 URL。");
        } catch (_error) {
            logWarn("未能 Hook java.net.URL.openConnection()，无法继续监控 HttpURLConnection。");
        }
    }

    console.log("=== 开始识别应用网络栈 ===");
    checkOkHttp();
    checkTTNet();
    checkHttpURLConnection();
    console.log("=== 网络栈识别初始化完成，将继续观察 " + (observeDurationMs / 1000) + " 秒 ===");

    setTimeout(function () {
        console.log("=== 网络栈识别观察窗口结束，将自动停止本次 Hook ===");
        try {
            send({
                type: "auto_stop",
                reason: "network-stack-window-finished",
                message: "网络栈识别观察窗口结束，正在自动停止 Hook。"
            });
        } catch (_error) {
        }
    }, observeDurationMs);
});


// frida -H 127.0.0.1:1234 -F -l detect_network_stack.js
