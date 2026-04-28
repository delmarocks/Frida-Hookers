// HTTPS 双向认证的工作原理：
// 在传统的 HTTPS 中，只有服务器 向 客户端提供证书，客户端验证服务器的证书以确认服务器身份。
// 双向认证 进一步要求客户端 也向 服务器提供证书，服务器验证客户端的证书，以确保客户端的身份。

// 脚本作用：
// 客户端证书认证时，拦截应用从 KeyStore 里取私钥和证书的时机，把这套客户端证书材料导出成一个可复用的 p12 文件

// 具体工作步骤：
// 等 App 去取客户端私钥
// hook java.security.KeyStore$PrivateKeyEntry 的两个方法：
// getPrivateKey() 和 getCertificateChain() 把私钥和证书拿到
// 重新打包成 .p12
// 存到应用私有目录里（/data/user/0/<包名>/client_keystore_<时间>.p12）


// 在 https 双向认证场景下，导出客户端证书为 p12 文件，默认密码为 hooker。
var password = "hooker";

// 简单日期格式化工具，用于生成导出文件名中的时间戳。
function dateFormat(fmt, date) {
    let ret;
    const opt = {
        "Y+": date.getFullYear().toString(),
        "m+": (date.getMonth() + 1).toString(),
        "d+": date.getDate().toString(),
        "H+": date.getHours().toString(),
        "M+": date.getMinutes().toString(),
        "S+": date.getSeconds().toString()
    };
    for (let k in opt) {
        ret = new RegExp("(" + k + ")").exec(fmt);
        if (ret) {
            fmt = fmt.replace(ret[1], (ret[1].length == 1) ? (opt[k]) : (opt[k].padStart(ret[1].length, "0")))
        };
    };
    return fmt;
}

// 生成一个区间随机数，避免导出文件重名。
function random(min, max) {
    return Math.floor(Math.random() * (max - min)) + min;
}

// 生成形如 YYYY_mm_dd_HH_MM_SS_xx 的时间字符串。
function getNowTime() {
    return dateFormat("YYYY_mm_dd_HH_MM_SS", new Date()) + "_" + random(1, 100);
}

// 获取当前应用包名，用于拼接导出文件路径。
function getPackageName() {
    var currentApplication = Java.use('android.app.ActivityThread').currentApplication();
    var context = currentApplication.getApplicationContext();
    return context.getPackageName();
};

// 记录一次方法调用的上下文，包含进程、线程、堆栈和时间信息。
function newMethodBeat(text, executor) {
    var threadClz = Java.use("java.lang.Thread");
    var androidLogClz = Java.use("android.util.Log");
    var exceptionClz = Java.use("java.lang.Exception");
    var processClz = Java.use("android.os.Process");
    var currentThread = threadClz.currentThread();
    var beat = new Object();
    beat.invokeId = Math.random().toString(36).slice( - 8);
    beat.executor = executor;
    beat.myPid = processClz.myPid();
    beat.threadId = currentThread.getId();
    beat.threadName = currentThread.getName();
    beat.text = text;
    beat.startTime = new Date().getTime();
    beat.stackInfo = androidLogClz.getStackTraceString(exceptionClz.$new()).substring(20);
    return beat;
};

// 输出方法调用轨迹，便于定位是谁触发了证书读取。
function printBeat(beat) {
    var str = ("------------pid:" + beat.myPid + ",startFlag:" + beat.invokeId + ",objectHash:"+beat.executor+",thread(id:" + beat.threadId +",name:" + beat.threadName + "),timestamp:" + beat.startTime+"---------------\n");
    str += beat.text + "\n";
    str += beat.stackInfo;
    str += ("------------endFlag:" + beat.invokeId + ",usedtime:" + (new Date().getTime() - beat.startTime) +"---------------\n");
    console.log(str);
};

// 将私钥和证书重新打包成 PKCS12，并写入应用私有目录。
// 1.把传入的证书强转成 X509Certificate
// 2.构造一个证书链数组
// 3.新建一个 PKCS12 类型的 KeyStore
// 4.调 setKeyEntry(...) 把私钥和证书链放进去
// 5.最后用 FileOutputStream 写出到目标路径
function dump2sdcard(pri, p7, filePath) {
    console.log("dump:" + filePath);
    var X509CertificateClass = Java.use("java.security.cert.X509Certificate");
    var myX509 = Java.cast(p7, X509CertificateClass);
    var chain = Java.array("java.security.cert.X509Certificate", [myX509]);
    var ks = Java.use("java.security.KeyStore").getInstance("PKCS12", "BC");
    ks.load(null, null);
    ks.setKeyEntry("client", pri, Java.use('java.lang.String').$new(password).toCharArray(), chain);
    try {
        var out = Java.use("java.io.FileOutputStream").$new(filePath);
        ks.store(out, Java.use('java.lang.String').$new(password).toCharArray());
    } catch(error) {
        console.log(error);
    }
}

Java.perform(function() {
    var packageName = getPackageName();
    console.log("在 https 双向认证场景下，dump 客户端证书为 p12。存储位置:/data/user/0/" + packageName + "/client_keystore_{nowtime}.p12 证书密码: hooker");

    // hook 读取私钥的入口，一旦应用取出客户端私钥就尝试导出 p12。
    Java.use("java.security.KeyStore$PrivateKeyEntry").getPrivateKey.implementation = function() {
        var executor = this.hashCode();
        var beatText = 'public java.security.cert.Certificate java.security.KeyStore$PrivateKeyEntry.getPrivateKey()';
        var beat = newMethodBeat(beatText, executor);
        var result = this.getPrivateKey();
        let filePath = '/data/user/0/' + packageName + "/client_keystore_" + "_" + getNowTime() + '.p12';
        dump2sdcard(this.getPrivateKey(), this.getCertificate(), filePath);
        printBeat(beat);
        return result;
    }

    // hook 读取证书链的入口，某些场景下应用先取证书链，也在这里补一次导出。
    Java.use("java.security.KeyStore$PrivateKeyEntry").getCertificateChain.implementation = function() {
        var executor = this.hashCode();
        var beatText = 'public java.security.cert.Certificate java.security.KeyStore$PrivateKeyEntry.getCertificate()';
        var beat = newMethodBeat(beatText, executor);
        var result = this.getCertificateChain();
        let filePath = '/data/user/0/' + packageName + "/client_keystore_" + getNowTime() + '.p12';
        dump2sdcard(this.getPrivateKey(), this.getCertificate(), filePath);
        return result;
    }
})


// 抓包或日志里看到“客户端证书”相关行为
// 如果看到代码里在用这些东西，基本要高度怀疑是双向认证：
// KeyStore
// PrivateKeyEntry
// getPrivateKey()
// getCertificateChain()
// KeyManagerFactory
// X509KeyManager
// SSLSocketFactory 重点
// SSLContext.init(keyManagers, trustManagers, ...) 重点
// OkHttpClient.Builder.sslSocketFactory(...) 重点
// .p12 / .bks / .jks 重点