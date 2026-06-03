function tryUse(className) {
    try {
        return Java.use(className);
    } catch (_error) {
        return null;
    }
}

function logInfo(message) {
    console.log("[*] " + message);
}

function logHit(message) {
    console.log("[+] " + message);
}

function logWarn(message) {
    console.log("[!] " + message);
}

function isProbablyUtf8(buffer) {
    const BufferCls = tryUse("okio.Buffer");
    const Character = tryUse("java.lang.Character");
    if (BufferCls === null || Character === null) {
        return false;
    }

    const prefix = BufferCls.$new();
    const byteCount = Math.min(buffer.size(), 64);
    buffer.copyTo(prefix, 0, byteCount);
    for (let i = 0; i < 16; i++) {
        if (prefix.exhausted()) {
            break;
        }
        const codePoint = prefix.readUtf8CodePoint();
        if (Character.isISOControl(codePoint) && !Character.isWhitespace(codePoint)) {
            return false;
        }
    }
    return true;
}

function detectOkHttpVersion() {
    const hints = [];
    const OkHttp = tryUse("okhttp3.OkHttp");
    if (OkHttp !== null) {
        try {
            hints.push("okhttp3.OkHttp.VERSION=" + OkHttp.VERSION.value);
        } catch (_error) {
            hints.push("okhttp3.OkHttp");
        }
    }

    const Version = tryUse("okhttp3.internal.Version");
    if (Version !== null) {
        try {
            hints.push("okhttp3.internal.Version=" + Version.userAgent());
        } catch (_error) {
            hints.push("okhttp3.internal.Version");
        }
    }

    if (tryUse("okhttp3.OkHttpClient") !== null) {
        hints.push("okhttp3.OkHttpClient");
    }

    return hints;
}

function hookInterceptor(name) {
    Java.perform(function () {
        const CallServerInterceptor = tryUse(name);
        const BufferCls = tryUse("okio.Buffer");
        const GzipSource = tryUse("okio.GzipSource");
        const SystemCls = tryUse("java.lang.System");
        const LongCls = tryUse("java.lang.Long");

        console.log("=== 开始启用 OkHttp 抓包 ===");

        if (CallServerInterceptor === null) {
            const hints = detectOkHttpVersion();
            if (hints.length > 0) {
                logWarn("检测到应用中可能存在 OkHttp，但未找到标准 CallServerInterceptor。");
                logInfo("已命中的 OkHttp 相关类：" + hints.join(", "));
                logInfo("这通常意味着目标 App 使用了改包名、裁剪版，或当前流量未经过标准 OkHttp 内部实现。");
            } else {
                logWarn("当前进程中未检测到标准 OkHttp 类，已跳过 OkHttp 抓包。");
            }
            console.log("=== OkHttp 抓包未启用 ===");
            return;
        }

        if (BufferCls === null || GzipSource === null || SystemCls === null || LongCls === null) {
            logWarn("缺少 OkHttp 抓包所需依赖类，已跳过 Hook。");
            console.log("=== OkHttp 抓包未启用 ===");
            return;
        }

        const intercept = CallServerInterceptor.intercept.overload("okhttp3.Interceptor$Chain");
        intercept.implementation = function (chain) {
            const logLines = [];
            const request = chain.request();
            const method = request.method();
            const url = request.url().toString();
            const requestHeaders = request.headers();

            logLines.push("\n====================[ OkHttp 请求 ]====================");
            logLines.push("请求行: " + method + " " + url);

            let curlParts = ["curl -X " + method, "'" + url + "'"];
            logLines.push("请求头:");
            for (let i = 0; i < requestHeaders.size(); i++) {
                const headerName = requestHeaders.name(i);
                const headerValue = requestHeaders.value(i);
                logLines.push("  " + headerName + ": " + headerValue);
                curlParts.push("-H '" + headerName + ": " + headerValue + "'");
            }

            let curlBodyStr = "";
            const requestBody = request.body();
            if (requestBody !== null && !requestBody.isDuplex() && !requestBody.isOneShot()) {
                const buffer = BufferCls.$new();
                requestBody.writeTo(buffer);
                if (isProbablyUtf8(buffer)) {
                    const bodyText = buffer.readUtf8();
                    const truncated = bodyText.length > 1000 ? bodyText.substring(0, 1000) + "..." : bodyText;
                    logLines.push("请求体:");
                    logLines.push(truncated);
                    curlBodyStr = bodyText.replace(/'/g, "'\\''");
                    logLines.push("请求体结束（" + requestBody.contentLength() + " 字节）");
                } else {
                    logLines.push("请求体为二进制，已跳过文本输出（" + requestBody.contentLength() + " 字节）");
                }
            } else {
                logLines.push("请求体结束（无可读请求体）");
            }

            if (curlBodyStr.length > 0) {
                curlParts.push("--data '" + curlBodyStr + "'");
            }

            logLines.push("curl（bash）:");
            logLines.push(curlParts.join(" "));
            logLines.push("curl（PowerShell）:");
            logLines.push(curlParts.join(" ").replace(/^curl\b/, "curl.exe"));

            const startNs = SystemCls.nanoTime();
            let response;
            try {
                response = intercept.call(this, chain);
            } catch (error) {
                logLines.push("请求失败: " + error);
                console.log(logLines.join("\n"));
                throw error;
            }
            const tookMs = (SystemCls.nanoTime() - startNs) / 1000000;

            const responseBody = response.body();
            const responseHeaders = response.headers();

            logLines.push("\n====================[ OkHttp 响应 ]====================");
            logLines.push("状态: " + response.code() + " " + response.message() + " (" + tookMs + "ms)");
            logLines.push("URL: " + response.request().url());
            logLines.push("响应头:");
            for (let i = 0; i < responseHeaders.size(); i++) {
                const headerName = responseHeaders.name(i);
                const headerValue = responseHeaders.value(i);
                logLines.push("  " + headerName + ": " + headerValue);
            }

            if (responseBody === null) {
                logLines.push("响应体为空");
                console.log(logLines.join("\n"));
                return response;
            }

            const encoding = responseHeaders.get("Content-Encoding");
            const source = responseBody.source();
            source.request(LongCls.MAX_VALUE.value);
            let buffer = Java.cast(source.buffer(), BufferCls);

            let gzippedLength = null;
            if (encoding !== null && encoding.toLowerCase() === "gzip") {
                gzippedLength = buffer.size();
                const gzipSource = GzipSource.$new(Java.cast(buffer.clone(), BufferCls));
                const decompressedBuffer = BufferCls.$new();
                decompressedBuffer.writeAll(gzipSource);
                buffer = decompressedBuffer;
            }

            if (!isProbablyUtf8(buffer)) {
                logLines.push("响应体为二进制，已跳过文本输出（" + buffer.size() + " 字节）");
                console.log(logLines.join("\n"));
                return response;
            }

            const bodyText = Java.cast(buffer.clone(), BufferCls).readUtf8();
            logLines.push("响应体:");
            logLines.push(bodyText.length > 1000 ? bodyText.substring(0, 1000) + "..." : bodyText);

            if (gzippedLength !== null) {
                logLines.push("响应体结束（解压后 " + buffer.size() + " 字节，原始 gzip " + gzippedLength + " 字节）");
            } else {
                logLines.push("响应体结束（" + buffer.size() + " 字节）");
            }

            console.log(logLines.join("\n"));
            return response;
        };

        logHit("已 Hook " + name + ".intercept()，后续会输出 OkHttp 请求与响应内容。");
        console.log("=== OkHttp 抓包已就绪 ===");
    });
}

setImmediate(function () {
    hookInterceptor("okhttp3.internal.http.CallServerInterceptor");
});
