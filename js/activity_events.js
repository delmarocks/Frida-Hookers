// 用于跟踪 Android Activity 生命周期（如 onCreate、onResume）的 Frida 脚本
// 帮助分析 Activity 初始化逻辑。

// 动态加载外部 dex，便于引入额外的辅助类。
function loadDexfile(dexfile) {
    Java.perform(function() {
          Java.openClassFile(dexfile).load();
          //console.log("load " + dexfile);
    });
};

// 仅在目标类尚未加载时再加载 dex，避免重复加载。
function checkLoadDex(className, dexfile) {
    Java.perform(function() {
        if (!classExists(className)) {
            Java.openClassFile(dexfile).load();
            //console.log("load " + dexfile);
        }
    });
};

// 判断指定 Java 类是否存在。
function classExists(className) {
    var exists = false;
    try {
        var clz = Java.use(className);
        exists = true;
    } catch(err) {
        //console.log(err);
    }
    return exists;
};

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
    var androidLogClz = Java.use("android.util.Log");
    var exceptionClz = Java.use("java.lang.Exception");
    var currentThread = threadClz.currentThread();
    var beat = new Object();
    beat.invokeId = Math.random().toString(36).slice( - 8);
    beat.executor = executor;
    beat.threadId = currentThread.getId();
    beat.threadName = currentThread.getName();
    beat.text = text;
    beat.startTime = new Date().getTime();
    beat.stackInfo = androidLogClz.getStackTraceString(exceptionClz.$new()).substring(20);
    return beat;
};

// 输出方法调用信息，包括对象、线程、耗时和调用栈。
function printBeat(beat) {
    var str = ("------------startFlag:" + beat.invokeId + ",objectHash:"+beat.executor+",thread(id:" + beat.threadId +",name:" + beat.threadName + "),timestamp:" + beat.startTime+"---------------\n");
    str += beat.text + "\n";
    str += beat.stackInfo;
    str += ("------------endFlag:" + beat.invokeId + ",usedtime:" + (new Date().getTime() - beat.startTime) +"---------------\n");
    console.log(str);
};

// 简单封装 console.log，便于后续统一替换日志输出方式。
function log(str) {
    console.log(str);
};

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

// 预加载 radar.dex，后续依赖其中的辅助类输出 Intent / Bundle 信息。
loadDexfile('/data/local/tmp/radar.dex');

// ContextWrapper.startActivity(Intent, Bundle)
// ContextWrapper.startActivity(Intent)
// ContextWrapper.startActivityAsUser(Intent, UserHandle)
// ContextWrapper.startActivityAsUser(Intent, Bundle, UserHandle)
// Activity.startActivityForResult(Intent, int, Bundle)
// 借助 /data/local/tmp/radar.dex 来实现
Java.perform(function() {
    var radarAndroidClz = Java.use("gz.radar.Android");
    var android_content_ContextWrapper_clz = Java.use('android.content.ContextWrapper');

    // hook ContextWrapper.startActivity(Intent, Bundle)
    var android_content_ContextWrapper_clz_method_startActivity_r7jq = android_content_ContextWrapper_clz.startActivity.overload('android.content.Intent', 'android.os.Bundle');
    android_content_ContextWrapper_clz_method_startActivity_r7jq.implementation = function(v0, v1) {
        log("Intent>>>>>>>"+radarAndroidClz.getIntentProfile(v0));
        log("Bundle>>>>>>>"+radarAndroidClz.getBundleProfile(v1));
        var executor = this.hashCode();
        var beatText = 'public void android.content.ContextWrapper.startActivity(android.content.Intent,android.os.Bundle)';
        var beat = newMethodBeat(beatText, executor);
        android_content_ContextWrapper_clz_method_startActivity_r7jq.call(this, v0, v1);
        printBeat(beat);
    };

    // hook ContextWrapper.startActivity(Intent)
    var android_content_ContextWrapper_clz_method_startActivity_auep = android_content_ContextWrapper_clz.startActivity.overload('android.content.Intent');
    android_content_ContextWrapper_clz_method_startActivity_auep.implementation = function(v0) {
        log("Intent>>>>>>>"+radarAndroidClz.getIntentProfile(v0));
        var executor = this.hashCode();
        var beatText = 'public void android.content.ContextWrapper.startActivity(android.content.Intent)';
        var beat = newMethodBeat(beatText, executor);
        android_content_ContextWrapper_clz_method_startActivity_auep.call(this, v0);
        printBeat(beat);
    };

    // hook ContextWrapper.startActivityAsUser(Intent, UserHandle)
    var android_content_ContextWrapper_clz_method_startActivityAsUser_adh6 = android_content_ContextWrapper_clz.startActivityAsUser.overload('android.content.Intent', 'android.os.UserHandle');
    android_content_ContextWrapper_clz_method_startActivityAsUser_adh6.implementation = function(v0, v1) {
        log("Intent>>>>>>>"+radarAndroidClz.getIntentProfile(v0));
        var executor = this.hashCode();
        var beatText = 'public void android.content.ContextWrapper.startActivityAsUser(android.content.Intent,android.os.UserHandle)';
        var beat = newMethodBeat(beatText, executor);
        android_content_ContextWrapper_clz_method_startActivityAsUser_adh6.call(this, v0, v1);
        printBeat(beat);
    };

    // hook ContextWrapper.startActivityAsUser(Intent, Bundle, UserHandle)
    var android_content_ContextWrapper_clz_method_startActivityAsUser_ilkk = android_content_ContextWrapper_clz.startActivityAsUser.overload('android.content.Intent', 'android.os.Bundle', 'android.os.UserHandle');
    android_content_ContextWrapper_clz_method_startActivityAsUser_ilkk.implementation = function(v0, v1, v2) {
        log("Intent>>>>>>>"+radarAndroidClz.getIntentProfile(v0));
        log("Bundle>>>>>>>"+radarAndroidClz.getBundleProfile(v1));
        var executor = this.hashCode();
        var beatText = 'public void android.content.ContextWrapper.startActivityAsUser(android.content.Intent,android.os.Bundle,android.os.UserHandle)';
        var beat = newMethodBeat(beatText, executor);
        android_content_ContextWrapper_clz_method_startActivityAsUser_ilkk.call(this, v0, v1, v2);
        printBeat(beat);
    };

    var android_app_Activity_clz = Java.use('android.app.Activity');

    // hook Activity.startActivityForResult(Intent, int, Bundle)
    var android_app_Activity_clz_method_startActivityForResult_6mkb = android_app_Activity_clz.startActivityForResult.overload('android.content.Intent', 'int', 'android.os.Bundle');
    android_app_Activity_clz_method_startActivityForResult_6mkb.implementation = function(v0, v1, v2) {
        log("Intent>>>>>>>"+radarAndroidClz.getIntentProfile(v0));
        log("Flags>>>>>>>"+v1);
        log("Bundle>>>>>>>"+radarAndroidClz.getBundleProfile(v2));
        var executor = this.hashCode();
        var beatText = 'public void android.app.Activity.startActivityForResult(android.content.Intent,int,android.os.Bundle)';
        var beat = newMethodBeat(beatText, executor);
        android_app_Activity_clz_method_startActivityForResult_6mkb.call(this, v0, v1, v2);
        printBeat(beat);
    };
});
