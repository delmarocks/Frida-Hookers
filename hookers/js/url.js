function tryGetClass(className) {
    var clz = undefined;
    try {
        clz = Java.use(className);
    } catch(e) {}
    return clz;
}

var URL_CATEGORY = "url-trace";

function emitEvent(message, details) {
    if (typeof Hookers !== "undefined") {
        Hookers.event(URL_CATEGORY, message, details);
        return;
    }
    console.log("[url-trace] " + message);
}

function newMethodBeat(text, executor) {
    var threadClz = Java.use("java.lang.Thread");
    var currentThread = threadClz.currentThread();
    var beat = new Object();
    beat.invokeId = Math.random().toString(36).slice( - 8);
    beat.executor = executor;
    beat.threadId = currentThread.getId();
    beat.threadName = currentThread.getName();
    beat.text = text;
    beat.startTime = new Date().getTime();
    return beat;
};

function printBeat(beat) {
    emitEvent(beat.text, {
        invokeId: beat.invokeId,
        executor: beat.executor,
        threadId: beat.threadId,
        threadName: beat.threadName,
        usedTimeMs: new Date().getTime() - beat.startTime
    });
};

var containRegExps = new Array()

var notContainRegExps = new Array(RegExp(/\.jpg/), RegExp(/\.png/))

function check(str) {
    str = str.toString();
    if (! (str && str.match)) {
        return false;
    }
    for (var i = 0; i < containRegExps.length; i++) {
        if (!str.match(containRegExps[i])) {
            return false;
        }
    }
    for (var i = 0; i < notContainRegExps.length; i++) {
        if (str.match(notContainRegExps[i])) {
            return false;
        }
    }
    return true;
}

Java.perform(function() {
    var uriParseClz = Java.use('java.net.URI');
    var uriParseClzConstruct = uriParseClz.$init.overload("java.lang.String");
    uriParseClzConstruct.implementation = function(url) {
        var result = uriParseClzConstruct.call(this, url);
        var executor = this.hashCode();
        var beatText = "url:" + url + "\npublic java.net.URI(String)";
        var beat = newMethodBeat(beatText, executor);
        if (check(url)) {
            printBeat(beat);
        }
        return result;
    };

    // URL
    var URLClz = Java.use('java.net.URL');
    var urlConstruct = URLClz.$init.overload("java.lang.String");
    urlConstruct.implementation = function(url) {
        var result = urlConstruct.call(this, url);
        var executor = this.hashCode();
        var beatText = "url:" + url + "\npublic java.net.URL(String)";
        var beat = newMethodBeat(beatText, executor);
        if (check(url)) {
            printBeat(beat);
        }
        return result;
    };

    //ok系统原生支持
    var sysBuilderClz = tryGetClass('com.android.okhttp.Request$Builder');
    if (sysBuilderClz) {
        var sysBuildFunc = sysBuilderClz.build.overload();
        sysBuildFunc.implementation = function() {
            var okRequestResult = sysBuildFunc.call(this);
            var httpUrl = okRequestResult.url();
            var url = httpUrl.toString();
            var executor = this.hashCode();
            var beatText = "url:" + url + "\ncom.android.okhttp.Request.Builder.build()";
            var beat = newMethodBeat(beatText, executor);
            if (check(url)) {
                printBeat(beat);
            }
            return okRequestResult
        };
    }

    //ok本地依赖
    var builderClz = tryGetClass('okhttp3.Request$Builder');
    if (builderClz) {
        var buildFunc = builderClz.build.overload();
        buildFunc.implementation = function() {
            var okRequestResult = buildFunc.call(this);
            var httpUrl = okRequestResult.url();
            var url = httpUrl.toString();
            var executor = this.hashCode();
            var beatText = "url:" + url + "\nokhttp3.Request.Builder.build()";
            var beat = newMethodBeat(beatText, executor);
            if (check(url)) {
                printBeat(beat);
            }
            return okRequestResult
        };
    }

    var android_net_Uri_clz = Java.use('android.net.Uri');
    var android_net_Uri_clz_method_parse_u5rj = android_net_Uri_clz.parse.overload('java.lang.String');
    android_net_Uri_clz_method_parse_u5rj.implementation = function(url) {
        var executor = 'Class';
        var beatText = url + '\npublic static android.net.Uri android.net.Uri.parse(java.lang.String)';
        var beat = newMethodBeat(beatText, executor);
        var ret = android_net_Uri_clz_method_parse_u5rj.call(android_net_Uri_clz, url);
        if (check(url)) {
            printBeat(beat);
        }
        return ret;
    };
});
