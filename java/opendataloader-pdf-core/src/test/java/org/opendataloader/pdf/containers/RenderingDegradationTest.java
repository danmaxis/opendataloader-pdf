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
package org.opendataloader.pdf.containers;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.opendataloader.pdf.processors.HiddenTextProcessor;
import org.verapdf.wcag.algorithms.entities.IObject;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;

/**
 * Verifies the graceful-degradation contract used when a platform has no working
 * AWT backend (e.g. the Windows/macOS native-image builds): once page rendering
 * is marked unavailable, the contrast/render consumer is no longer handed out and
 * the hidden-text processor passes content through untouched — so the conversion
 * keeps producing text/structure output instead of crashing.
 */
class RenderingDegradationTest {

    @BeforeEach
    void setUp() {
        StaticLayoutContainers.clearContainers();
    }

    @Test
    void markRenderingUnavailable_makesConsumerNull() {
        StaticLayoutContainers.markRenderingUnavailable(new NoSuchMethodError("simulated missing AWT"));
        // The lazy initializer must short-circuit and never try to build a consumer.
        assertNull(StaticLayoutContainers.getContrastRatioConsumer("any.pdf", null, false, null));
    }

    @Test
    void hiddenText_passesThroughWhenRenderingUnavailable() {
        StaticLayoutContainers.markRenderingUnavailable(new NoSuchMethodError("simulated missing AWT"));
        List<IObject> contents = new ArrayList<>();
        List<IObject> result = HiddenTextProcessor.findHiddenText("any.pdf", contents, true, null);
        // Consumer is null -> the original list is returned unchanged.
        assertSame(contents, result);
    }
}
