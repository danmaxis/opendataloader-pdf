/*
 * Copyright 2025-2026 Hancom Inc.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.opendataloader.pdf.utils;

import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.util.zip.CRC32;
import java.util.zip.Deflater;

/**
 * A dependency-free PNG encoder built only on {@link java.util.zip.Deflater}
 * and {@link java.util.zip.CRC32}.
 *
 * <p>It exists so the native (GraalVM) build does not have to drag in the
 * {@code javax.imageio} PNG writer, whose {@code ServiceLoader}-based plugin
 * discovery is a well-known native-image pain point. The encoder is fully
 * deterministic (fixed "None" scanline filter, fixed Deflate level), so the
 * bytes produced here are identical on the JVM and in the native image —
 * which lets the golden-file parity tests compare image output exactly.
 *
 * <p>Pixels are read a scanline at a time via
 * {@link BufferedImage#getRGB(int, int, int, int, int[], int, int)} so it works
 * for any image type without per-pixel call overhead. Output is 8-bit truecolor:
 * RGB when the source is fully opaque, RGBA otherwise.
 */
public final class PngEncoder {

    private static final byte[] SIGNATURE = {(byte) 0x89, 'P', 'N', 'G', '\r', '\n', 0x1A, '\n'};

    private PngEncoder() {
    }

    /**
     * Encodes the image as a PNG byte array.
     */
    public static byte[] encode(BufferedImage image) {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        try {
            write(image, out);
        } catch (IOException e) {
            // ByteArrayOutputStream never throws IOException; rethrow defensively.
            throw new IllegalStateException("Unexpected I/O error encoding PNG in memory", e);
        }
        return out.toByteArray();
    }

    /**
     * Encodes the image as a PNG and writes it to the given stream.
     */
    public static void write(BufferedImage image, OutputStream out) throws IOException {
        int width = image.getWidth();
        int height = image.getHeight();
        boolean hasAlpha = image.getColorModel().hasAlpha() && imageUsesAlpha(image, width, height);

        out.write(SIGNATURE);

        // IHDR: width, height, bit depth 8, color type (2 = RGB, 6 = RGBA),
        // compression 0, filter 0, interlace 0.
        byte[] ihdr = new byte[13];
        writeInt(ihdr, 0, width);
        writeInt(ihdr, 4, height);
        ihdr[8] = 8;
        ihdr[9] = (byte) (hasAlpha ? 6 : 2);
        ihdr[10] = 0;
        ihdr[11] = 0;
        ihdr[12] = 0;
        writeChunk(out, "IHDR", ihdr);

        // IDAT: each scanline prefixed with filter byte 0 (None), then deflated.
        int channels = hasAlpha ? 4 : 3;
        byte[] raw = new byte[height * (1 + width * channels)];
        int[] row = new int[width];
        int pos = 0;
        for (int y = 0; y < height; y++) {
            raw[pos++] = 0; // filter: None
            // Batch-read the whole scanline in one call instead of per-pixel
            // getRGB(x, y) — far less overhead on large page images.
            image.getRGB(0, y, width, 1, row, 0, width);
            for (int x = 0; x < width; x++) {
                int argb = row[x];
                raw[pos++] = (byte) ((argb >> 16) & 0xFF); // R
                raw[pos++] = (byte) ((argb >> 8) & 0xFF);  // G
                raw[pos++] = (byte) (argb & 0xFF);         // B
                if (hasAlpha) {
                    raw[pos++] = (byte) ((argb >> 24) & 0xFF); // A
                }
            }
        }
        writeChunk(out, "IDAT", deflate(raw));

        writeChunk(out, "IEND", new byte[0]);
    }

    private static boolean imageUsesAlpha(BufferedImage image, int width, int height) {
        int[] row = new int[width];
        for (int y = 0; y < height; y++) {
            image.getRGB(0, y, width, 1, row, 0, width);
            for (int x = 0; x < width; x++) {
                if ((row[x] >>> 24) != 0xFF) {
                    return true;
                }
            }
        }
        return false;
    }

    private static byte[] deflate(byte[] data) {
        Deflater deflater = new Deflater(Deflater.BEST_COMPRESSION);
        try {
            deflater.setInput(data);
            deflater.finish();
            ByteArrayOutputStream buffer = new ByteArrayOutputStream(Math.max(64, data.length / 2));
            byte[] chunk = new byte[8192];
            while (!deflater.finished()) {
                int n = deflater.deflate(chunk);
                buffer.write(chunk, 0, n);
            }
            return buffer.toByteArray();
        } finally {
            deflater.end();
        }
    }

    private static void writeChunk(OutputStream out, String type, byte[] data) throws IOException {
        byte[] length = new byte[4];
        writeInt(length, 0, data.length);
        out.write(length);

        byte[] typeBytes = type.getBytes(java.nio.charset.StandardCharsets.US_ASCII);
        out.write(typeBytes);
        out.write(data);

        CRC32 crc = new CRC32();
        crc.update(typeBytes);
        crc.update(data);
        byte[] crcBytes = new byte[4];
        writeInt(crcBytes, 0, (int) crc.getValue());
        out.write(crcBytes);
    }

    private static void writeInt(byte[] target, int offset, int value) {
        target[offset] = (byte) ((value >>> 24) & 0xFF);
        target[offset + 1] = (byte) ((value >>> 16) & 0xFF);
        target[offset + 2] = (byte) ((value >>> 8) & 0xFF);
        target[offset + 3] = (byte) (value & 0xFF);
    }
}
