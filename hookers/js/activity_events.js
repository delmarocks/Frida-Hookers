// 用于跟踪 Android 页面跳转与 Activity 相关事件。

var ACTIVITY_EVENTS_CATEGORY = "activity-events";

function emitInfo(message, details) {
    if (typeof Hookers !== "undefined") {
        Hookers.info(ACTIVITY_EVENTS_CATEGORY, message, details);
        return;
    }
    console.log("[activity-events] " + message);
}

function emitWarn(message, details) {
    if (typeof Hookers !== "undefined") {
        Hookers.warn(ACTIVITY_EVENTS_CATEGORY, message, details);
        return;
    }
    console.warn("[activity-events] " + message);
}

function emitError(message, details) {
    if (typeof Hookers !== "undefined") {
        Hookers.error(ACTIVITY_EVENTS_CATEGORY, message, details);
        return;
    }
    console.error("[activity-events] " + message);
}

function emitEvent(message, details) {
    if (typeof Hookers !== "undefined") {
        Hookers.event(ACTIVITY_EVENTS_CATEGORY, message, details);
        return;
    }
    console.log("[activity-events] " + message);
}

// 获取对象的运行时类名，兼容普通对象和需要强转的对象。
function getClassName(obj) {
    if (obj.getClass) {
        return obj.getClass().getName();
    }
    var javaObject = Java.use("java.lang.Object");
    return Java.cast(obj, javaObject).getClass().getName();
}

// 判断 str1 是否包含 str2，str2 支持正则表达式。
function contains(str1, str2) {
    var reg = RegExp(eval("/"+str2+"/"));
    if(str1 && str1.match && str1.match(reg)){
        return true;
    }else{
        return false;
    }
};

// 创建 Java ArrayList 实例。
function newArrayList() {
    var ArrayListClz = Java.use('java.util.ArrayList');
    return ArrayListClz.$new();
}

// 创建 Java HashSet 实例。
function newHashSet() {
    var HashSetClz = Java.use('java.util.HashSet');
    return HashSetClz.$new();
}

// 创建 Java HashMap 实例。
function newHashMap() {
    var HashMapClz = Java.use('java.util.HashMap');
    return HashMapClz.$new();
}

// 记录一次方法调用的上下文信息，后续用于统一打印调用耗时和堆栈。
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

// 输出结构化事件信息，包括对象、线程、耗时和调用栈。
function printBeat(beat, details) {
    var payload = details || {};
    payload.invokeId = beat.invokeId;
    payload.executor = beat.executor;
    payload.threadId = beat.threadId;
    payload.threadName = beat.threadName;
    payload.usedTimeMs = new Date().getTime() - beat.startTime;
    emitEvent(beat.text, payload);
}

// 使用应用内的 Gson 将 Java 对象转成 JSON，适合做快速调试输出。
function toJson(javaObject) {
    var gsonClz = Java.use("com.google.gson.Gson");
    var toJsonMethod = gsonClz.toJson.overload("java.lang.Object");
    return toJsonMethod.call(gsonClz.$new(),javaObject);
};

// 获取当前应用的 ApplicationContext。
function getBaseContext() {
    var currentApplication = Java.use('android.app.ActivityThread').currentApplication();
    var context = currentApplication.getApplicationContext();
    return context; //Java.scheduleOnMainThread(fn):
};

// 忙等待版 sleep，仅适合短时间调试使用。
function sleep(time) {
    var startTime = new Date().getTime() + parseInt(time, 10);
    while(new Date().getTime() < startTime) {}
};

// 使用 fastjson 输出对象内容。
function fastTojson(javaObject) {
    var JSONClz = Java.use("gz.com.alibaba.fastjson.JSON");
    return JSONClz.toJSONString(javaObject);
};

// ContextWrapper.startActivity(Intent, Bundle)
// ContextWrapper.startActivity(Intent)
// ContextWrapper.startActivityAsUser(Intent, UserHandle)
// ContextWrapper.startActivityAsUser(Intent, Bundle, UserHandle)
// Activity.startActivityForResult(Intent, int, Bundle)
Java.perform(function() {
    if (typeof Hookers !== "undefined" && !Hookers.ensureRadarDex(["gz.radar.Android"])) {
        return;
    }
    if (typeof Hookers === "undefined") {
        try {
            Java.openClassFile('/data/local/tmp/radar.dex').load();
        } catch (_error) {
            emitError("radar.dex 未就绪，已跳过页面跳转监听。", {
                dexPath: "/data/local/tmp/radar.dex",
                hint: "请先点击“准备环境并刷新 App”，确认 radar.dex 已部署到设备后重试。"
            });
            return;
        }
        if (!classExists("gz.radar.Android")) {
            emitError("radar.dex 已加载，但依赖类缺失，已跳过页面跳转监听。", {
                dexPath: "/data/local/tmp/radar.dex",
                missingClasses: ["gz.radar.Android"],
                hint: "请重新部署 radar.dex，或检查当前脚本与 radar.dex 版本是否匹配。"
            });
            return;
        }
    }

    var radarAndroidClz = Java.use("gz.radar.Android");
    var android_content_ContextWrapper_clz = Java.use('android.content.ContextWrapper');
    var hookedCount = 0;
    var skippedCount = 0;
    emitInfo("监听页面跳转脚本已就绪。", {
        requires: ["gz.radar.Android"],
        source: "activity_events.js"
    });

    // hook ContextWrapper.startActivity(Intent, Bundle)
    try {
        var android_content_ContextWrapper_clz_method_startActivity_r7jq = android_content_ContextWrapper_clz.startActivity.overload('android.content.Intent', 'android.os.Bundle');
        android_content_ContextWrapper_clz_method_startActivity_r7jq.implementation = function(v0, v1) {
            var executor = this.hashCode();
            var beatText = 'public void android.content.ContextWrapper.startActivity(android.content.Intent,android.os.Bundle)';
            var beat = newMethodBeat(beatText, executor);
            android_content_ContextWrapper_clz_method_startActivity_r7jq.call(this, v0, v1);
            printBeat(beat, {
                intent: radarAndroidClz.getIntentProfile(v0),
                bundle: radarAndroidClz.getBundleProfile(v1)
            });
        };
        hookedCount += 1;
    } catch (_error) {
        skippedCount += 1;
        emitWarn("当前系统不支持 ContextWrapper.startActivity(Intent, Bundle)，已跳过。", {
            overload: "ContextWrapper.startActivity(Intent, Bundle)",
            error: String(_error)
        });
    }

    // hook ContextWrapper.startActivity(Intent)
    try {
        var android_content_ContextWrapper_clz_method_startActivity_auep = android_content_ContextWrapper_clz.startActivity.overload('android.content.Intent');
        android_content_ContextWrapper_clz_method_startActivity_auep.implementation = function(v0) {
            var executor = this.hashCode();
            var beatText = 'public void android.content.ContextWrapper.startActivity(android.content.Intent)';
            var beat = newMethodBeat(beatText, executor);
            android_content_ContextWrapper_clz_method_startActivity_auep.call(this, v0);
            printBeat(beat, {
                intent: radarAndroidClz.getIntentProfile(v0)
            });
        };
        hookedCount += 1;
    } catch (_error) {
        skippedCount += 1;
        emitWarn("当前系统不支持 ContextWrapper.startActivity(Intent)，已跳过。", {
            overload: "ContextWrapper.startActivity(Intent)",
            error: String(_error)
        });
    }

    // hook ContextWrapper.startActivityAsUser(Intent, UserHandle)
    try {
        var android_content_ContextWrapper_clz_method_startActivityAsUser_adh6 = android_content_ContextWrapper_clz.startActivityAsUser.overload('android.content.Intent', 'android.os.UserHandle');
        android_content_ContextWrapper_clz_method_startActivityAsUser_adh6.implementation = function(v0, v1) {
            var executor = this.hashCode();
            var beatText = 'public void android.content.ContextWrapper.startActivityAsUser(android.content.Intent,android.os.UserHandle)';
            var beat = newMethodBeat(beatText, executor);
            android_content_ContextWrapper_clz_method_startActivityAsUser_adh6.call(this, v0, v1);
            printBeat(beat, {
                intent: radarAndroidClz.getIntentProfile(v0)
            });
        };
        hookedCount += 1;
    } catch (_error) {
        skippedCount += 1;
        emitWarn("当前系统不支持 ContextWrapper.startActivityAsUser(Intent, UserHandle)，已跳过。", {
            overload: "ContextWrapper.startActivityAsUser(Intent, UserHandle)",
            error: String(_error)
        });
    }

    // hook ContextWrapper.startActivityAsUser(Intent, Bundle, UserHandle)
    try {
        var android_content_ContextWrapper_clz_method_startActivityAsUser_ilkk = android_content_ContextWrapper_clz.startActivityAsUser.overload('android.content.Intent', 'android.os.Bundle', 'android.os.UserHandle');
        android_content_ContextWrapper_clz_method_startActivityAsUser_ilkk.implementation = function(v0, v1, v2) {
            var executor = this.hashCode();
            var beatText = 'public void android.content.ContextWrapper.startActivityAsUser(android.content.Intent,android.os.Bundle,android.os.UserHandle)';
            var beat = newMethodBeat(beatText, executor);
            android_content_ContextWrapper_clz_method_startActivityAsUser_ilkk.call(this, v0, v1, v2);
            printBeat(beat, {
                intent: radarAndroidClz.getIntentProfile(v0),
                bundle: radarAndroidClz.getBundleProfile(v1)
            });
        };
        hookedCount += 1;
    } catch (_error) {
        skippedCount += 1;
        emitWarn("当前系统不支持 ContextWrapper.startActivityAsUser(Intent, Bundle, UserHandle)，已跳过。", {
            overload: "ContextWrapper.startActivityAsUser(Intent, Bundle, UserHandle)",
            error: String(_error)
        });
    }

    var android_app_Activity_clz = Java.use('android.app.Activity');

    // hook Activity.startActivityForResult(Intent, int, Bundle)
    try {
        var android_app_Activity_clz_method_startActivityForResult_6mkb = android_app_Activity_clz.startActivityForResult.overload('android.content.Intent', 'int', 'android.os.Bundle');
        android_app_Activity_clz_method_startActivityForResult_6mkb.implementation = function(v0, v1, v2) {
            var executor = this.hashCode();
            var beatText = 'public void android.app.Activity.startActivityForResult(android.content.Intent,int,android.os.Bundle)';
            var beat = newMethodBeat(beatText, executor);
            android_app_Activity_clz_method_startActivityForResult_6mkb.call(this, v0, v1, v2);
            printBeat(beat, {
                intent: radarAndroidClz.getIntentProfile(v0),
                flags: v1,
                bundle: radarAndroidClz.getBundleProfile(v2)
            });
        };
        hookedCount += 1;
    } catch (_error) {
        skippedCount += 1;
        emitWarn("当前系统不支持 Activity.startActivityForResult(Intent, int, Bundle)，已跳过。", {
            overload: "Activity.startActivityForResult(Intent, int, Bundle)",
            error: String(_error)
        });
    }

    emitInfo("监听页面跳转脚本初始化完成。", {
        hookedCount: hookedCount,
        skippedCount: skippedCount
    });
});
