package de.youspeed.classifierbenchmark;

import java.util.HashSet;

/** Manifest-bound append-only DE classifier contract, independent of Android. */
final class ClassContract {
    static void validateLabels(String[] labels) {
        int count = labels.length;
        require(count == 134 || (count >= 136 && count <= 512), "Unsupported DE class count");
        HashSet<String> unique = new HashSet<>();
        for (String label : labels)
            require(label != null && !label.isEmpty() && label.equals(label.trim()) && unique.add(label), "Invalid or duplicate class");
        if (count >= 136)
            require(labels[134].equals("city:start") && labels[135].equals("city:end"), "City class order mismatch");
    }

    static void validateSharedPrefix(String[] first, String[] second) {
        for (int index = 0; index < Math.min(first.length, second.length); index++)
            require(first[index].equals(second[index]), "Original class indices changed between models");
    }

    static void validateOutputShape(int[] shape, int expectedCount) {
        require(shape.length == 2 && shape[0] == 1 && shape[1] == expectedCount,
                "Output/class-index shape mismatch");
    }

    private static void require(boolean value, String message) {
        if (!value) throw new IllegalArgumentException(message);
    }
}
