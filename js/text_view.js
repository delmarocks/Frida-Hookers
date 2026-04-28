// 用于提取页面展示的明文数据，以及获取堆栈调用信息，从而追踪业务层的 model 构造逻辑和数据源。
// 跟踪 TextView 的 setText() 和 getText() 调用，并输出其真实 Class

// 统一打印一次方法调用的线程、调用栈和耗时信息。
function methodInBeat(invokeId, timestamp, methodName, executor) {
    var startTime = timestamp;
    var androidLogClz = Java.use("android.util.Log");
    var exceptionClz = Java.use("java.lang.Exception");
    var threadClz = Java.use("java.lang.Thread");
    var currentThread = threadClz.currentThread();
    // 获取堆栈调用信息
    var stackInfo = androidLogClz.getStackTraceString(exceptionClz.$new());
    var str = ("------------startFlag:" + invokeId + ",objectHash:"+executor+",thread(id:" + currentThread.getId() +",name:" + currentThread.getName() + "),timestamp:" + startTime+"---------------\n");
    str += methodName + "\n";
    str += stackInfo.substring(20);
    str += ("------------endFlag:" + invokeId + ",usedtime:" + (new Date().getTime() - startTime) +"---------------\n");
    console.log(str);
};

Java.perform(function() {
    var androidLogClz = Java.use("android.util.Log");
    var exceptionClz = Java.use("java.lang.Exception");
    var textViewClz = Java.use("android.widget.TextView");

    // hook TextView.setText(CharSequence)，观察页面上文本内容何时被设置。
    if (textViewClz.setText) {
        var setTextFunc = textViewClz.setText.overload("java.lang.CharSequence");
        setTextFunc.implementation = function(v0) {
            var startTime = new Date().getTime();
            var clz = this.getClass().getName();
            var viewId = this.getId();
            console.log("TextViewClz: " + clz);
            console.log("ViewId: " + viewId);
            console.log("Text:" + v0);
            setTextFunc.call(this, v0);
            var invokeId = Math.random().toString(36).slice( - 8);
            var executor = this.hashCode();
            methodInBeat(invokeId, startTime, "android.widget.TextView.setText()", executor);
        };
    }

    // hook TextView.getText()，观察业务代码何时读取控件文本。
    if (textViewClz.getText) {
        var getTextFunc = textViewClz.getText.overload();
        getTextFunc.implementation = function() {
            var startTime = new Date().getTime();
            var clz = this.getClass().getName();
            var viewId = this.getId();
            var editable = getTextFunc.call(this);
            console.log("TextViewClz: " + clz);
            console.log("ViewId: " + viewId);
            console.log("Text: " + editable.toString());
            var invokeId = Math.random().toString(36).slice( - 8);
            var executor = this.hashCode();
            methodInBeat(invokeId, startTime, "android.widget.TextView.getText()", executor);
            return editable;
        };
    }
});

// getClass()：Java Object 的方法
// getName()：通常是 Java Class 的方法
// getId()：Android View 的方法