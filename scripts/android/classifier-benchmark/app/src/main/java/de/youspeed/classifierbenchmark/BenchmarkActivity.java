package de.youspeed.classifierbenchmark;

import android.app.Activity;
import android.app.ActivityManager;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;
import android.os.BatteryManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Debug;
import android.os.PowerManager;
import android.os.Process;
import android.os.SystemClock;
import android.view.WindowManager;
import android.widget.TextView;
import android.util.Log;
import org.json.JSONArray;
import org.json.JSONObject;
import org.tensorflow.lite.DataType;
import org.tensorflow.lite.Interpreter;
import org.tensorflow.lite.TensorFlowLite;
import org.tensorflow.lite.gpu.CompatibilityList;
import org.tensorflow.lite.gpu.GpuDelegate;
import org.tensorflow.lite.gpu.GpuDelegateFactory;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Locale;

/** Isolated diagnostic process: no production package, model selection, camera or network access. */
public final class BenchmarkActivity extends Activity {
    private static final int SIZE = 224;
    private static final int INPUT_BYTES = SIZE * SIZE * 3 * Float.BYTES;
    private TextView status;
    private File inputRoot;
    private File outputRoot;
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);
    private final Bitmap resized = Bitmap.createBitmap(SIZE, SIZE, Bitmap.Config.ARGB_8888);
    private final int[] pixels = new int[SIZE * SIZE];
    private final float[] chunk = new float[4096 * 3];

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        status = new TextView(this);
        status.setText("Preparing isolated classifier benchmark");
        setContentView(status);
        inputRoot = new File(getExternalFilesDir(null), "input");
        inputRoot.mkdirs();
        if (!getIntent().getBooleanExtra("run", false)) {
            status.setText("Ready. Stage input/manifest.json, then launch with --ez run true.");
            return;
        }
        new Thread(() -> {
            try { execute(); }
            catch (Throwable failure) {
                try {
                    if (outputRoot == null) outputRoot = new File(getExternalFilesDir(null), "failed-" + System.currentTimeMillis());
                    outputRoot.mkdirs();
                    write(new File(outputRoot, "failure.json"), new JSONObject()
                        .put("status", "failed").put("type", failure.getClass().getName())
                        .put("message", String.valueOf(failure.getMessage())));
                } catch (Exception ignored) { }
                update("FAILED: " + failure);
            }
        }, "classifier-benchmark-owner").start();
    }

    private void execute() throws Exception {
        File manifest = confined(inputRoot, getIntent().getStringExtra("manifest") == null
            ? "manifest.json" : getIntent().getStringExtra("manifest"));
        JSONObject config = new JSONObject(new String(Files.readAllBytes(manifest.toPath()), StandardCharsets.UTF_8));
        require(config.getInt("schemaVersion") == 1, "Unsupported schema");
        String runId = config.getString("runId");
        require(runId.matches("[a-zA-Z0-9_-]{1,100}"), "Unsafe runId");
        File proposedOutput = new File(getExternalFilesDir(null), "results/" + runId);
        require(!proposedOutput.exists(), "Existing run directory: use a new runId");
        require(proposedOutput.mkdirs(), "Cannot create output directory");
        outputRoot = proposedOutput;
        new File(outputRoot, "native-preprocessed").mkdirs();
        write(new File(outputRoot, "configuration.json"), config);
        JSONObject device = snapshot();
        device.put("manifestSha256", sha(manifest)).put("runtime", "LiteRT1.4.2")
            .put("nativeRuntimeVersion", TensorFlowLite.runtimeVersion())
            .put("buildType", "debug isolated Java APK; optimized native LiteRT")
            .put("tensor", "Float32 NHWC [1,224,224,3], RGB /255")
            .put("scope", "Classifier only; crop fixture is not a detector/whole-camera benchmark")
            .put("preprocessing", "Native: decoded PNG to Canvas scale-fill224, FILTER_BITMAP_FLAG, RGB/255. Canonical: supplied224PNG to RGB/255, no resize.")
            .put("liveRoiContextReconstructed", false)
            .put("threads", 4).put("xnnpack", true);
        write(new File(outputRoot, "device-start.json"), device);
        int warmups = config.optInt("warmupCount", 20);
        int rounds = config.optInt("rounds", 3);
        int repeats = config.optInt("repeatsPerImage", 1);
        require(warmups >= 1 && warmups <= 200 && rounds >= 1 && rounds <= 10 && repeats >= 1 && repeats <= 10, "Unbounded run");
        JSONArray modelJson = config.getJSONArray("models");
        JSONArray imageJson = config.getJSONArray("images");
        require(modelJson.length() >= 1 && modelJson.length() <= 4 && imageJson.length() >= 1 && imageJson.length() <= 512, "Invalid corpus size");
        List<Model> models = new ArrayList<>();
        for (int i = 0; i < modelJson.length(); i++) models.add(new Model(modelJson.getJSONObject(i)));
        for (Model model : models)
            ClassContract.validateSharedPrefix(models.get(0).orderedLabels, model.orderedLabels);
        List<Crop> crops = new ArrayList<>();
        JSONArray preprocessing = new JSONArray();
        for (int i = 0; i < imageJson.length(); i++) {
            Crop crop = new Crop(imageJson.getJSONObject(i), i);
            crops.add(crop);
            preprocessing.put(crop.preparation);
        }
        write(new File(outputRoot, "input-preparation.json"), new JSONObject().put("images", preprocessing));
        JSONArray modes = config.optJSONArray("modes");
        if (modes == null) modes = new JSONArray().put("gpu");
        JSONArray trialIndex = new JSONArray();
        int trialNumber = 0;
        for (int round = 0; round < rounds; round++) {
            List<Model> order = new ArrayList<>(models);
            if (round % 2 == 1) Collections.reverse(order);
            for (int mi = 0; mi < modes.length(); mi++) {
                String mode = modes.getString((mi + round) % modes.length());
                require(Arrays.asList("gpu", "gpu_fp32").contains(mode), "Only explicit GPU modes are allowed");
                for (Model model : order) {
                    String trialId = String.format(Locale.ROOT, "%03d-%s-%s-r%d", trialNumber++, model.id, mode, round);
                    update("Running " + trialId);
                    Log.i("YouSpeedClassifierBench", "BEGIN " + trialId);
                    JSONObject result = runTrial(model, crops, mode, round, warmups, repeats);
                    Log.i("YouSpeedClassifierBench", "END " + trialId + " status=" + result.getString("status"));
                    result.put("trialId", trialId);
                    write(new File(outputRoot, trialId + ".json"), result);
                    trialIndex.put(new JSONObject().put("file", trialId + ".json").put("status", result.getString("status")));
                    write(new File(outputRoot, "progress.json"), new JSONObject().put("trials", trialIndex));
                }
            }
        }
        JSONObject complete = new JSONObject().put("status", "complete").put("trials", trialIndex)
            .put("deviceEnd", snapshot()).put("manifestSha256", sha(manifest));
        write(new File(outputRoot, "complete.json"), complete);
        for (Crop crop : crops) crop.nativeBitmap.recycle();
        update("COMPLETE: " + runId);
    }

    private JSONObject runTrial(Model model, List<Crop> crops, String mode, int round, int warmups, int repeats) throws Exception {
        JSONObject result = new JSONObject().put("modelId", model.id).put("modelSha256", model.digest)
            .put("classLabels", model.labels).put("requestedMode", mode).put("round", round)
            .put("deviceStart", snapshot()).put("warmupCount", warmups).put("repeatsPerImage", repeats)
            .put("coldLoadDefinition", "Fresh interpreter in same process; OS filesystem caches are not flushed");
        Resources resources = null;
        try {
            long began = System.nanoTime();
            resources = load(model, mode);
            result.put("loadMs", millis(began)).put("actualBackend", resources.backend)
                .put("fallbackReason", resources.reason == null ? JSONObject.NULL : resources.reason);
            ByteBuffer output = ByteBuffer.allocateDirect(model.count * 4).order(ByteOrder.nativeOrder());
            Crop first = crops.get(round % crops.size());
            began = System.nanoTime();
            infer(resources, first.canonicalTensor, output);
            result.put("firstInferenceMs", millis(began));
            for (int i = 0; i < warmups; i++) infer(resources, crops.get(i % crops.size()).canonicalTensor, output);
            result.put("deviceAfterWarmup", snapshot());
            JSONArray samples = new JSONArray();
            List<Double> forwardTimes = new ArrayList<>(), nativePrepTimes = new ArrayList<>(), nativeTimes = new ArrayList<>(), nativeTotalTimes = new ArrayList<>();
            ByteBuffer nativeTensor = direct();
            for (int repeat = 0; repeat < repeats; repeat++) {
                for (int j = 0; j < crops.size(); j++) {
                    Crop crop = crops.get((j + round * 13) % crops.size());
                    // Alternate path order across rounds to reduce one-sided warm-cache bias.
                    JSONObject canonical;
                    JSONObject nativeResult;
                    if (round % 2 == 0) {
                        canonical = timedForward(resources, crop.canonicalTensor, output, round == 0 && repeat == 0);
                        nativeResult = timedNative(resources, crop, nativeTensor, output, round == 0 && repeat == 0);
                    } else {
                        nativeResult = timedNative(resources, crop, nativeTensor, output, round == 0 && repeat == 0);
                        canonical = timedForward(resources, crop.canonicalTensor, output, round == 0 && repeat == 0);
                    }
                    forwardTimes.add(canonical.getDouble("forwardMs"));
                    nativePrepTimes.add(nativeResult.getDouble("preprocessMs"));
                    nativeTimes.add(nativeResult.getDouble("forwardMs"));
                    nativeTotalTimes.add(nativeResult.getDouble("preprocessAndForwardMs"));
                    samples.put(new JSONObject().put("id", crop.id).put("source", crop.source).put("repeat", repeat)
                        .put("canonical", canonical).put("native", nativeResult));
                }
            }
            result.put("samples", samples).put("canonicalForward", stats(forwardTimes))
                .put("nativePreprocess", stats(nativePrepTimes)).put("nativeForward", stats(nativeTimes))
                .put("nativePreprocessAndForward", stats(nativeTotalTimes)).put("status", "complete");
        } catch (Throwable failure) {
            result.put("status", "failed").put("failure", failure.toString());
        } finally {
            if (resources != null) resources.close();
        }
        return result.put("deviceEnd", snapshot());
    }

    private JSONObject timedNative(Resources resources, Crop crop, ByteBuffer input, ByteBuffer output, boolean keep) throws Exception {
        long totalStart = System.nanoTime();
        encode(crop.nativeBitmap, input, true);
        double preprocessingMs = millis(totalStart);
        long forwardStart = System.nanoTime();
        infer(resources, input, output);
        double forwardMs = millis(forwardStart);
        double pipelineMs = millis(totalStart);
        return describeOutput(output, forwardMs, keep).put("preprocessMs", preprocessingMs).put("preprocessAndForwardMs", pipelineMs);
    }

    private JSONObject timedForward(Resources resources, ByteBuffer input, ByteBuffer output, boolean keep) throws Exception {
        long began = System.nanoTime();
        infer(resources, input, output);
        double duration = millis(began);
        return describeOutput(output, duration, keep);
    }

    private JSONObject describeOutput(ByteBuffer output, double duration, boolean keep) throws Exception {
        float[] values = new float[output.capacity() / 4];
        output.rewind(); output.asFloatBuffer().get(values);
        int best = 0;
        double sum = 0;
        JSONArray scores = new JSONArray();
        for (int i = 0; i < values.length; i++) {
            require(Float.isFinite(values[i]), "Nonfinite output");
            if (values[i] > values[best]) best = i;
            sum += values[i];
            if (keep) scores.put((double) values[i]);
        }
        JSONObject result = new JSONObject().put("forwardMs", duration).put("argmax", best)
            .put("maxScore", (double) values[best]).put("scoreSum", sum);
        if (keep) result.put("scores", scores);
        return result;
    }

    private void infer(Resources resources, ByteBuffer input, ByteBuffer output) {
        input.rewind(); output.clear(); resources.interpreter.run(input, output);
    }

    private Resources load(Model model, String mode) throws Exception {
        GpuDelegate delegate = null;
        try (CompatibilityList compatibility = new CompatibilityList()) {
            if (!compatibility.isDelegateSupportedOnThisDevice())
                throw new IllegalStateException("GPU unsupported by CompatibilityList; CPU fallback disabled");
            GpuDelegateFactory.Options gpu = compatibility.getBestOptionsForThisDevice()
                .setPrecisionLossAllowed(!mode.equals("gpu_fp32"))
                .setInferencePreference(GpuDelegateFactory.Options.INFERENCE_PREFERENCE_FAST_SINGLE_ANSWER);
            delegate = new GpuDelegate(gpu);
            return new Resources(new Interpreter(model.buffer.duplicate(), options().addDelegate(delegate)), delegate, mode, null, model.count);
        } catch (RuntimeException | LinkageError failure) {
            if (delegate != null) delegate.close();
            throw failure;
        }
    }

    private Interpreter.Options options() { return new Interpreter.Options().setNumThreads(4).setUseXNNPACK(true); }

    private final class Model {
        final String id, digest;
        final int count;
        final JSONArray labels;
        final String[] orderedLabels;
        final ByteBuffer buffer;
        Model(JSONObject value) throws Exception {
            id = value.getString("id"); require(id.matches("[a-zA-Z0-9_-]{1,80}"), "Unsafe model id");
            File file = confined(inputRoot, value.getString("path"));
            digest = value.getString("sha256"); require(digest.equals(sha(file)), "Model hash mismatch: " + id);
            count = value.getInt("classCount"); labels = value.getJSONArray("classLabels");
            require(labels.length() == count, "Class order mismatch");
            orderedLabels = new String[count];
            for (int i = 0; i < count; i++) orderedLabels[i] = labels.getString(i);
            ClassContract.validateLabels(orderedLabels);
            try (FileInputStream stream = new FileInputStream(file)) {
                buffer = stream.getChannel().map(FileChannel.MapMode.READ_ONLY, 0, file.length());
            }
        }
    }

    private static final class Resources implements AutoCloseable {
        final Interpreter interpreter;
        final GpuDelegate delegate;
        final String backend, reason;
        Resources(Interpreter i, GpuDelegate d, String b, String r, int expectedCount) {
            interpreter = i; delegate = d; backend = b; reason = r;
            require(Arrays.equals(i.getInputTensor(0).shape(), new int[]{1,SIZE,SIZE,3}), "Input shape mismatch");
            require(i.getInputTensor(0).dataType() == DataType.FLOAT32 && i.getOutputTensor(0).dataType() == DataType.FLOAT32, "Expected Float32 tensors");
            ClassContract.validateOutputShape(i.getOutputTensor(0).shape(), expectedCount);
        }
        public void close() { try { interpreter.close(); } finally { if (delegate != null) delegate.close(); } }
    }

    private final class Crop {
        final String id, source;
        final Bitmap nativeBitmap;
        final ByteBuffer canonicalTensor;
        final JSONObject preparation;
        Crop(JSONObject value, int index) throws Exception {
            id = value.getString("id"); source = value.optString("source", "unknown");
            File nativeFile = confined(inputRoot, value.getString("path"));
            File canonicalFile = confined(inputRoot, value.getString("canonicalPath"));
            require(sha(nativeFile).equals(value.getString("sha256")), "Native crop hash mismatch");
            require(sha(canonicalFile).equals(value.getString("canonicalSha256")), "Canonical crop hash mismatch");
            long start = System.nanoTime();
            nativeBitmap = BitmapFactory.decodeFile(nativeFile.getPath());
            double nativeDecodeMs = millis(start);
            start = System.nanoTime();
            Bitmap canonical = BitmapFactory.decodeFile(canonicalFile.getPath());
            double canonicalDecodeMs = millis(start);
            require(nativeBitmap != null && canonical != null, "Invalid image bytes");
            require(canonical.getWidth() == SIZE && canonical.getHeight() == SIZE, "Canonical PNG must be224square");
            canonicalTensor = direct(); encode(canonical, canonicalTensor, false); canonical.recycle();
            ByteBuffer nativeTensor = direct(); encode(nativeBitmap, nativeTensor, true);
            String preparedName = String.format(Locale.ROOT, "native-preprocessed/%04d.png", index);
            File prepared = new File(outputRoot, preparedName);
            try (FileOutputStream stream = new FileOutputStream(prepared)) { resized.compress(Bitmap.CompressFormat.PNG, 100, stream); }
            preparation = new JSONObject().put("id", id).put("source", source)
                .put("nativeWidth", nativeBitmap.getWidth()).put("nativeHeight", nativeBitmap.getHeight())
                .put("nativeDecodeMs", nativeDecodeMs).put("canonicalDecodeMs", canonicalDecodeMs)
                .put("canonicalTensorSha256", sha(canonicalTensor)).put("nativeTensorSha256", sha(nativeTensor))
                .put("nativePreparedPng", preparedName).put("nativePreparedPngSha256", sha(prepared));
        }
    }

    private void encode(Bitmap source, ByteBuffer target, boolean resize) {
        Bitmap bitmap = source;
        if (resize) {
            Canvas canvas = new Canvas(resized); canvas.drawColor(Color.BLACK);
            canvas.drawBitmap(source, new Rect(0,0,source.getWidth(),source.getHeight()), new RectF(0,0,SIZE,SIZE), paint);
            bitmap = resized;
        }
        bitmap.getPixels(pixels, 0, SIZE, 0, 0, SIZE, SIZE);
        target.clear(); java.nio.FloatBuffer out = target.asFloatBuffer();
        int offset = 0;
        while (offset < pixels.length) {
            int end = Math.min(pixels.length, offset + chunk.length / 3), used = 0;
            while (offset < end) {
                int color = pixels[offset++];
                chunk[used++] = ((color >>> 16) & 255) / 255f;
                chunk[used++] = ((color >>> 8) & 255) / 255f;
                chunk[used++] = (color & 255) / 255f;
            }
            out.put(chunk, 0, used);
        }
        target.rewind();
    }

    private JSONObject snapshot() throws Exception {
        Debug.MemoryInfo memory = new Debug.MemoryInfo(); Debug.getMemoryInfo(memory);
        ActivityManager.MemoryInfo global = new ActivityManager.MemoryInfo();
        ((ActivityManager)getSystemService(Context.ACTIVITY_SERVICE)).getMemoryInfo(global);
        Intent battery = registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        PowerManager power = (PowerManager)getSystemService(Context.POWER_SERVICE);
        return new JSONObject().put("timestampEpochMs", System.currentTimeMillis())
            .put("elapsedRealtimeMs", SystemClock.elapsedRealtime()).put("pid", Process.myPid())
            .put("manufacturer", Build.MANUFACTURER).put("model", Build.MODEL).put("device", Build.DEVICE)
            .put("socManufacturer", Build.SOC_MANUFACTURER).put("socModel", Build.SOC_MODEL)
            .put("androidRelease", Build.VERSION.RELEASE).put("sdk", Build.VERSION.SDK_INT)
            .put("buildFingerprint", Build.FINGERPRINT).put("abis", new JSONArray(Arrays.asList(Build.SUPPORTED_ABIS)))
            .put("thermalStatus", power.getCurrentThermalStatus()).put("powerSaveMode", power.isPowerSaveMode())
            .put("batteryTemperatureC", battery == null ? JSONObject.NULL : battery.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, -1) / 10.0)
            .put("batteryPlugged", battery == null ? -1 : battery.getIntExtra(BatteryManager.EXTRA_PLUGGED, -1))
            .put("totalPssKb", memory.getTotalPss()).put("nativePssKb", memory.nativePss)
            .put("nativeHeapAllocatedBytes", Debug.getNativeHeapAllocatedSize())
            .put("javaHeapMaximumBytes", Runtime.getRuntime().maxMemory())
            .put("javaHeapUsedBytes", Runtime.getRuntime().totalMemory() - Runtime.getRuntime().freeMemory())
            .put("availableMemoryBytes", global.availMem).put("lowMemory", global.lowMemory);
    }

    private static JSONObject stats(List<Double> times) throws Exception {
        List<Double> sorted = new ArrayList<>(times); Collections.sort(sorted);
        double sum = 0; for (double t : times) sum += t;
        return new JSONObject().put("n", times.size()).put("p50Ms", quantile(sorted, .5))
            .put("p95Ms", quantile(sorted, .95)).put("meanMs", sum / times.size())
            .put("minimumMs", sorted.get(0)).put("maximumMs", sorted.get(sorted.size()-1));
    }
    private static double quantile(List<Double> sorted, double p) {
        double position = (sorted.size()-1)*p; int lower = (int)Math.floor(position), upper = (int)Math.ceil(position);
        return sorted.get(lower) + (sorted.get(upper)-sorted.get(lower))*(position-lower);
    }
    private static ByteBuffer direct() { return ByteBuffer.allocateDirect(INPUT_BYTES).order(ByteOrder.nativeOrder()); }
    private static double millis(long start) { return (System.nanoTime() - start) / 1_000_000.0; }
    private static File confined(File root, String relative) throws Exception {
        File value = new File(root, relative).getCanonicalFile();
        require(value.toPath().startsWith(root.getCanonicalFile().toPath()) && !relative.startsWith("/"), "Path outside input root");
        require(value.isFile(), "Missing file: " + relative); return value;
    }
    private static String sha(File file) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-256"); byte[] buffer = new byte[65536];
        try (FileInputStream stream = new FileInputStream(file)) { int n; while ((n = stream.read(buffer)) >= 0) md.update(buffer, 0, n); }
        return hex(md.digest());
    }
    private static String sha(ByteBuffer buffer) throws Exception {
        ByteBuffer copy = buffer.duplicate(); copy.rewind(); MessageDigest md = MessageDigest.getInstance("SHA-256"); md.update(copy); return hex(md.digest());
    }
    private static String hex(byte[] value) { StringBuilder b = new StringBuilder(); for (byte v : value) b.append(String.format(Locale.ROOT, "%02x", v & 255)); return b.toString(); }
    private static void write(File path, JSONObject value) throws Exception {
        File temporary = new File(path.getPath() + ".tmp");
        Files.write(temporary.toPath(), (value.toString(2) + "\n").getBytes(StandardCharsets.UTF_8));
        Files.move(temporary.toPath(), path.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING);
    }
    private static void require(boolean condition, String message) { if (!condition) throw new IllegalArgumentException(message); }
    private void update(String value) { runOnUiThread(() -> status.setText(value)); }
}
