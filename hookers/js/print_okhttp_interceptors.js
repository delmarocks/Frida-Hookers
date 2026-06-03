function printOkHttpInterceptors() {
    Java.perform(function () {
        function logInfo(message) {
            console.log("[*] " + message);
        }

        function logHit(message) {
            console.log("[+] " + message);
        }

        function logWarn(message) {
            console.log("[!] " + message);
        }

        function tryUse(className) {
            try {
                return Java.use(className);
            } catch (_error) {
                return null;
            }
        }

        function detectOkHttpHints() {
            const hints = [];
            if (tryUse("okhttp3.OkHttp")) {
                hints.push("okhttp3.OkHttp");
            }
            if (tryUse("okhttp3.OkHttpClient")) {
                hints.push("okhttp3.OkHttpClient");
            }
            if (tryUse("okhttp3.internal.Version")) {
                hints.push("okhttp3.internal.Version");
            }
            if (tryUse("okhttp3.Interceptor")) {
                hints.push("okhttp3.Interceptor");
            }
            return hints;
        }

        const builderClassName = "okhttp3.OkHttpClient$Builder";
        const OkHttpClientBuilder = tryUse(builderClassName);
        const JavaList = tryUse("java.util.List");

        console.log("=== 开始分析 OkHttp 拦截器 ===");

        if (JavaList === null) {
            logWarn("无法加载 java.util.List，已跳过 OkHttp 拦截器分析。");
            return;
        }

        if (OkHttpClientBuilder === null) {
            const hints = detectOkHttpHints();
            if (hints.length > 0) {
                logWarn(
                    "检测到应用里可能存在 OkHttp 痕迹，但未找到标准 Builder 类 okhttp3.OkHttpClient$Builder。"
                );
                logInfo("已命中的 OkHttp 相关类：" + hints.join(", "));
                logInfo("这通常意味着目标 App 使用了改包名、裁剪版，或当前网络栈并非标准 OkHttp Builder。");
            } else {
                logWarn("当前进程中未检测到标准 OkHttp 类，已跳过拦截器枚举。");
            }
            console.log("=== OkHttp 拦截器分析结束 ===");
            return;
        }

        const build = OkHttpClientBuilder.build.overload();
        let printedCount = 0;

        build.implementation = function () {
            const client = build.call(this);
            printedCount += 1;

            try {
                const interceptors = Java.cast(client.interceptors(), JavaList);
                const networkInterceptors = Java.cast(client.networkInterceptors(), JavaList);

                console.log("\n=== 捕获到 OkHttpClient 构建 #" + printedCount + " ===");
                console.log("应用拦截器数量：" + interceptors.size());
                for (let i = 0; i < interceptors.size(); i++) {
                    const interceptor = interceptors.get(i);
                    console.log("  [App] " + interceptor.$className);
                }

                console.log("网络拦截器数量：" + networkInterceptors.size());
                for (let i = 0; i < networkInterceptors.size(); i++) {
                    const interceptor = networkInterceptors.get(i);
                    console.log("  [Net] " + interceptor.$className);
                }
            } catch (error) {
                logWarn("OkHttpClient 已构建，但读取拦截器列表失败：" + error);
            }

            return client;
        };

        logHit("已 Hook okhttp3.OkHttpClient$Builder.build()，后续构建 OkHttpClient 时会打印拦截器链。");
        console.log("=== OkHttp 拦截器分析已就绪 ===");
    });
}

setImmediate(printOkHttpInterceptors);
