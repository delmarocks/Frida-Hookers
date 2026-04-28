// 判断提供的 buffer 内容是否是 UTF-8 编码的字符串。
// 用于判断请求/响应体是否可以转为文本。
function isProbablyUtf8(buffer) {
    const BufferCls = Java.use("okio.Buffer");
    const Character = Java.use("java.lang.Character");

    const prefix = BufferCls.$new();
    const byteCount = Math.min(buffer.size(), 64);
    buffer.copyTo(prefix, 0, byteCount);
    for (let i = 0; i < 16; i++) {
        if (prefix.exhausted()) break;
        const codePoint = prefix.readUtf8CodePoint();
        // 如果存在无法识别的控制字符且不是空格，则认为该内容不是 UTF-8 编码。
        if (Character.isISOControl(codePoint) &&
            !Character.isWhitespace(codePoint)) {
            return false;
        }
    }
    return true;
}

// name : okhttp3.internal.http.CallServerInterceptor
function hookInterceptor(name) {
    Java.perform(function () {
        const CallServerInterceptor = Java.use(name);
        const BufferCls = Java.use("okio.Buffer");
        const GzipSource = Java.use("okio.GzipSource");
        // const Utf8Kt = Java.use("okhttp3.logging.Utf8Kt");

        CallServerInterceptor.intercept.implementation = function (chain) {
            const logLines = [];
            const request = chain.request();
            const method = request.method();            // 获取请求方法
            const url = request.url().toString();       // 获取 url
            const requestHeaders = request.headers();   // 获取请求头

            logLines.push("\n📤====================[ OkHttp Request ]====================📤");
            logLines.push(`➡️ ${method} ${url}`);
            
            // 生成 curl 命令
            let curlParts = [`curl -X ${method}`];
            curlParts.push(`'${url}'`);  // 拼接

            // 获取具体的请求头信息
            logLines.push("🔸 请求头:");
            for (let i = 0; i < requestHeaders.size(); i++) {
                const name = requestHeaders.name(i);
                const value = requestHeaders.value(i);
                logLines.push(`   ${name}: ${value}`);

                // 构造 curl header 参数
                curlParts.push(`-H '${name}: ${value}'`);
            }

            // 记录请求体（Body）
            let curlBodyStr = "";
            const requestBody = request.body();
            if (requestBody != null && !requestBody.isDuplex() && !requestBody.isOneShot()) {
                const buffer = BufferCls.$new();
                requestBody.writeTo(buffer);
                // 判断响应体是否可以转为文本
                if (isProbablyUtf8(buffer)) {
                    logLines.push("📝 响应体:");
                    const bodyText = buffer.readUtf8();
                    const truncated = bodyText.length > 1000 ? bodyText.substring(0, 1000) + "..." : bodyText
                    logLines.push(truncated);  // log具体信息
                    curlBodyStr = bodyText.replace(/'/g, "'\\''"); // escape single quotes for curl
                    logLines.push(`--> END ${method} (${requestBody.contentLength()}-byte body)`);
                } else {
                    logLines.push(`--> END ${method} (binary ${requestBody.contentLength()}-byte body omitted)`);
                }
            } else {
                logLines.push(`--> END ${method}`);
            }

            // 添加 curl body
            if (curlBodyStr.length > 0) {
                curlParts.push(`--data '${curlBodyStr}'`);
            }

            // 输出 curl 命令（标准）
            let curl = curlParts.join(" ")
            logLines.push("\n📦 CURL (Linux/macOS/bash):");
            logLines.push(curl);

            // 输出 curl.exe 命令（Windows PowerShell）
            logLines.push("\n📦 CURL (Windows/PowerShell):");
            logLines.push(curl.replace(/^curl\b/, "curl.exe"));

            
            // 执行curl指令进行请求
            const startNs = Java.use("java.lang.System").nanoTime();
            let response;
            try {
                response = this.intercept(chain);
            } catch (e) {
                logLines.push("<-- ❌ HTTP FAILED: " + e);
                throw e;
            }
            const tookMs = (Java.use("java.lang.System").nanoTime() - startNs) / 1000000;

            const responseBody = response.body();
            const contentLength = responseBody.contentLength();
            const responseHeaders = response.headers();

            // 请求返回处理
            logLines.push("\n📥====================[ OkHttp Response ]====================📥");
            logLines.push(`⬅️ ${response.code()} ${response.message()} (${tookMs}ms)`);
            logLines.push(`↩️ URL: ${response.request().url()}`);
            logLines.push("🔸 Headers:");
            for (let i = 0; i < responseHeaders.size(); i++) {
                const name = responseHeaders.name(i);
                const value = responseHeaders.value(i);
                logLines.push(`   ${name}: ${value}`);
            }

            const encoding = responseHeaders.get("Content-Encoding");

            const source = responseBody.source();
            source.request(Java.use("java.lang.Long").MAX_VALUE.value);
            let buffer = source.buffer();
            buffer = Java.cast(buffer, BufferCls);

            let gzippedLength = null;
            if (encoding !== null && encoding.toLowerCase() === "gzip") {
                gzippedLength = buffer.size();
                const gzipSource = GzipSource.$new(Java.cast(buffer.clone(), BufferCls));
                const decompressedBuffer = BufferCls.$new();
                decompressedBuffer.writeAll(gzipSource);
                buffer = decompressedBuffer;
            }

            if (!isProbablyUtf8(buffer)) {
                logLines.push("⚠️  Response body is binary. Skipped logging.");
                logLines.push(`<-- END HTTP (binary ${buffer.size()}-byte body omitted)`);
                return response;
            }

            if (contentLength !== 0) {
                const bodyText = Java.cast(buffer.clone(), BufferCls).readUtf8();
                logLines.push("📄 Body:");
                logLines.push(bodyText.length > 1000 ? bodyText.substring(0, 1000) + "..." : bodyText);
            }

            if (gzippedLength !== null) {
                logLines.push(`<-- END HTTP (${buffer.size()}-byte, ${gzippedLength}-gzipped-byte body)`);
            } else {
                logLines.push(`<-- END HTTP (${buffer.size()}-byte body)`);
            }

            logLines.push("==============================================================\n");

            console.log(logLines.join("\n"));

            return response;
        };
    });
}

// 获取OkHttp的版本
function detectOkHttpVersion() {
    Java.perform(function () {
        const hasClass = (name) => {
            try {
                Java.use(name);
                return true;
            } catch (_) {
                return false;
            }
        };

        const log = [];
        log.push("🔍 Scanning for OkHttp...");

        // 优先检测公开版本字段（4.x 开始提供）
        if (hasClass("okhttp3.OkHttp")) {
            try {
                const OkHttp = Java.use("okhttp3.OkHttp");
                const version = OkHttp.VERSION.value;
                log.push(`✅ Detected OkHttp: version=${version} (via okhttp3.OkHttp.VERSION)`);
            } catch (e) {
                log.push("⚠️ Found okhttp3.OkHttp but failed to read VERSION field.");
            }
            console.log(log.join("\n"));
            return;
        }

        // 再检测内部类（3.x ~ 4.x 通用）
        if (hasClass("okhttp3.internal.Version")) {
            try {
                const Version = Java.use("okhttp3.internal.Version");
                const userAgent = Version.userAgent();
                log.push(`✅ Detected OkHttp via internal.Version: ${userAgent}`);
            } catch (e) {
                log.push("⚠️ Found okhttp3.internal.Version but failed to read userAgent.");
            }
            console.log(log.join("\n"));
            return;
        }

        log.push("❌ OkHttp not detected in current app.");
        console.log(log.join("\n"));
    });
}


setImmediate(function () {
    hookInterceptor("okhttp3.internal.http.CallServerInterceptor")
});


// frida -H 127.0.0.1:1234 -F -l okhttp.js
// frida -H 127.0.0.1:1234 -F -l okhttp.js -o log.txt
// frida -H 127.0.0.1:1234 -F -l okhttp.js --runtime=v8 --debug
