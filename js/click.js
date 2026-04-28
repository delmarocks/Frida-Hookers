// 用于监听 Android 应用中点击事件（OnClickListener）
// 主要用于分析用户交互操作，获取被点击View的真实ViewClass

// 统一打印一次方法调用的线程、调用栈和耗时信息。
function methodInBeat(invokeId, timestamp, methodName, executor) {
    var startTime = timestamp;
    var androidLogClz = Java.use("android.util.Log");
    var exceptionClz = Java.use("java.lang.Exception");
    var threadClz = Java.use("java.lang.Thread");
    var currentThread = threadClz.currentThread();
    var stackInfo = androidLogClz.getStackTraceString(exceptionClz.$new());
    var str = ("------------startFlag:" + invokeId + ",objectHash:"+executor+",thread(id:" + currentThread.getId() +",name:" + currentThread.getName() + "),timestamp:" + startTime+"---------------\n");
    str += methodName + "\n";
    str += stackInfo.substring(20);
    str += ("------------endFlag:" + invokeId + ",usedtime:" + (new Date().getTime() - startTime) +"---------------\n");
    console.log(str);
};

// 忙等待版 sleep，仅适合调试场景。
function sleep(time) {
    var startTime = new Date().getTime() + parseInt(time, 10);
    while (new Date().getTime() < startTime) {}
};

// 根据类名获取对应的 Java Class 对象。
function makeClass(className) {
    var classClz = Java.use("java.lang.Class");
    var forNameFunc = classClz.forName.overload("java.lang.String");
    return forNameFunc.call(classClz, className);
};

// 判断对象是否属于指定父类或接口。
function isClass(obj, superClzName) {
    var objClz = obj.getClass();
    var superClz = makeClass(superClzName);
    return superClz.isAssignableFrom(objClz);
};

Java.perform(function() {
    var textViewClz = Java.use("android.widget.TextView");
    var android_view_View_clz = Java.use('android.view.View');

    // hook 所有 View 的 performClick，用于观察点击事件落到哪个控件上。
    var android_view_View_clz_method_performClick_u6ef = android_view_View_clz.performClick.overload();
    android_view_View_clz_method_performClick_u6ef.implementation = function() {
        var invokeId = Math.random().toString(36).slice( - 8);
        var startTime = new Date().getTime();
        var executor = 'obj:' + this.hashCode();

        // 先调用原始点击逻辑，避免影响正常点击流程。
        var ret = android_view_View_clz_method_performClick_u6ef.call(this);

        // 点击后输出当前控件的类名和 id，方便定位实际被点到的 View。
        var clz = this.getClass().getName();
        var viewId = this.getId();
        //console.log("ViewText: " + Java.cast(this, textViewClz).getText());
        console.log("ViewClz: " + clz);
        console.log("ViewId: " + viewId);

        methodInBeat(invokeId, startTime, 'public boolean android.view.View.performClick()', executor);
        return ret;
    };
});
