// 封装一些操作原生Android UI的函数
// startActivity()、home()、back()、finishCurrentActivity()、clickByText(text) 


// 动态加载外部 dex，供脚本访问额外的 Java 辅助类。
function loadDexfile(dexfile) {
    Java.perform(function() {
        Java.openClassFile(dexfile).load();
    });
};

// 如果目标类尚未存在，则加载指定 dex，避免重复加载。
function checkLoadDex(className, dexfile) {
    Java.perform(function() {
        if (!classExists(className)) {
            Java.openClassFile(dexfile).load();
            //console.log("load " + dexfile);
        }
    });
};

// 预加载 radar.dex，后续依赖其中的 Android / AndroidUI 辅助类。
loadDexfile('/data/local/tmp/radar.dex');

// 判断指定 Java 类是否已经加载。
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
    var reg = RegExp(eval("/" + str2 + "/"));
    if (str1 && str1.match && str1.match(reg)) {
        return true;
    } else {
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

// 简单封装日志输出。
function log(str) {
    console.log(str);
};

// 使用应用内的 Gson 将 Java 对象转成 JSON，便于调试输出。
function toJson(javaObject) {
    var gsonClz = Java.use("com.google.gson.Gson");
    var toJsonMethod = gsonClz.toJson.overload("java.lang.Object");
    return toJsonMethod.call(gsonClz.$new(), javaObject);
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
    while (new Date().getTime() < startTime) {}
};

// 使用 fastjson 输出 Java 对象。
function fastTojson(javaObject) {
    var JSONClz = Java.use("gz.com.alibaba.fastjson.JSON");
    return JSONClz.toJSONString(javaObject);
};

// 根据 View id 查询控件信息，并输出字段和方法列表。
function findViewById(viewId) {
    var report = "";
    Java.perform(function() {
        var radarAndroidClz = Java.use("gz.radar.Android");
        var viewInfo = radarAndroidClz.getViewInfo(viewId + "");
        if (!viewInfo) {
            report += "Not Found View."
            return;
        }
        report += ("------------------View--------------------") + "\n";
        report += ("View Id: " + viewInfo.getViewId()) + "\n";
        report += ("View IdName: " + viewInfo.getViewIdName()) + "\n";
        report += ("View Class: " + viewInfo.getName()) + "\n";
        report += ("View SuperClass: " + viewInfo.getSuperClazz()) + "\n";
        report += ("View ImplementInterfaces: " + viewInfo.getImplementInterfaces()) + "\n";
        var androidApkFields = viewInfo.getAndroidApkFields();
        report += ("View Fields: " + androidApkFields.length) + "\n";
        for (var j = 0; j < androidApkFields.length; j++) {
            report += ("\t" + androidApkFields[j].toLine()) + "\n";
        }
        var methods = viewInfo.methods();
        report += ("View Methods: " + methods.length) + "\n";
        for (var j = 0; j < methods.length; j++) {
            report += ("\t" + methods[j]) + "\n";
        }
    });
    log(report);
}

// 通过当前顶层 Activity 直接启动指定页面。
function startActivity(activityName) {
    Java.perform(function() {
        var androidUIClz = Java.use("gz.radar.AndroidUI");
        androidUIClz.startActivity(activityName);
    });
}

// 使用 Context 启动指定页面。
function contextStartActivity(activityName) {
    Java.perform(function() {
        var androidUIClz = Java.use("gz.radar.AndroidUI");
        androidUIClz.contextStartActivity(activityName);
    });
}

// 使用 Context + NEW_TASK 标志启动页面，适合非 Activity 场景。
function contextStartActivityForNewTask(activityName) {
    Java.perform(function() {
        var androidUIClz = Java.use("gz.radar.AndroidUI");
        androidUIClz.contextStartActivityForNewTask(activityName);
    });
}

// 通过当前栈顶 Activity 发起页面跳转。
function topActivityStartActivity(activityName) {
    Java.perform(function() {
        var androidUIClz = Java.use("gz.radar.AndroidUI");
        androidUIClz.topActivityStartActivity(activityName);
    });
}

// 模拟按下 Home 键。
function home() {
    Java.perform(function() {
        var androidUIClz = Java.use("gz.radar.AndroidUI");
        androidUIClz.home();
    });
}

// 模拟按下返回键。
function back() {
    Java.perform(function() {
        var androidUIClz = Java.use("gz.radar.AndroidUI");
        androidUIClz.back();
    });
}

// 结束当前栈顶 Activity。
function finishCurrentActivity() {
    Java.perform(function() {
        var androidUIClz = Java.use("gz.radar.AndroidUI");
        androidUIClz.finishCurrentActivity();
    });
}

// 根据控件文本查找并点击目标 View。
function clickByText(text) {
    Java.perform(function() {
        var androidUIClz = Java.use("gz.radar.AndroidUI");
        log(androidUIClz.clickByText(text));
    });
}

// 根据 View id 查找并点击目标控件。
function clickById(id) {
    Java.perform(function() {
        var androidUIClz = Java.use("gz.radar.AndroidUI");
        log(androidUIClz.clickById(id));
    });
}

// 执行一段从按下到抬起的滑动/悬停操作。
function hover(x, y, upStepLength) {
    Java.perform(function() {
        var androidui = Java.use("gz.radar.AndroidUI");
        androidui.hover(x, y, upStepLength);
    });
}

// 输出当前页面的 View 树结构，便于定位控件层级。
function viewTree() {
    Java.perform(function() {
        var androidUIClz = Java.use("gz.radar.AndroidUI");
        log(androidUIClz.viewTree());
    });
}

