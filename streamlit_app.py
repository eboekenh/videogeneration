#!/usr/bin/env python3
"""Streamlit front-end for the mythology video pipeline.

Run with: streamlit run streamlit_app.py
"""
from __future__ import annotations

import io
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mythology_video.alignment import align_storyboard
from mythology_video.enhance import enhance_video
from mythology_video.media import CommandError, probe_duration, require_binary
from mythology_video.motion_editor import (
    APPLICABLE_MOTIONS,
    MOTION_ROTATION,
    MotionSegment,
    apply_motion_segments,
    detect_static_segments,
    probe_video_info,
)
from mythology_video.renderer import RenderSettings, build_video_range
from mythology_video.storyboard import (
    Storyboard,
    load_storyboard,
    save_storyboard,
    summarize_issues,
    validate_storyboard,
)

st.set_page_config(page_title="Mitoloji Video Stüdyosu", page_icon="🎬", layout="wide")

TRANSITIONS = ["none", "fade", "fadeblack", "fadewhite", "smoothleft", "smoothright"]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _workdir() -> Path:
    if "workdir" not in st.session_state:
        st.session_state["workdir"] = Path(tempfile.mkdtemp(prefix="streamlit_mv_"))
    return st.session_state["workdir"]


def _format_eta(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}sa {minutes}dk"
    if minutes:
        return f"{minutes}dk {secs}sn"
    return f"{secs}sn"


def _ffmpeg_ready() -> tuple[bool, str]:
    try:
        require_binary("ffmpeg")
        require_binary("ffprobe")
        return True, ""
    except FileNotFoundError as exc:
        return False, str(exc)


def _save_upload(uploaded_file, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        handle.write(uploaded_file.getbuffer())
    return destination


def _persist_upload(uploaded_file, destination: Path, state_key: str) -> Path | None:
    """Save an uploaded file to disk only when it actually changed."""
    if uploaded_file is None:
        return st.session_state.get(state_key)
    fingerprint = (uploaded_file.name, uploaded_file.size)
    if st.session_state.get(state_key + "_fp") != fingerprint:
        _save_upload(uploaded_file, destination)
        st.session_state[state_key + "_fp"] = fingerprint
        st.session_state[state_key] = destination
    return st.session_state.get(state_key)


def _extract_images_zip(uploaded_file, images_dir: Path) -> None:
    if images_dir.exists():
        shutil.rmtree(images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(uploaded_file.getbuffer())) as archive:
        for member in archive.infolist():
            member_path = (images_dir / member.filename).resolve()
            if not str(member_path).startswith(str(images_dir.resolve())):
                raise ValueError(f"Zip içinde güvensiz bir yol var: {member.filename}")
        archive.extractall(images_dir)
    # Unwrap a single top-level folder (e.g. a zip of "images/*.jpg").
    entries = list(images_dir.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        nested = entries[0]
        for item in nested.iterdir():
            shutil.move(str(item), str(images_dir / item.name))
        nested.rmdir()


def _reset_session() -> None:
    workdir = st.session_state.get("workdir")
    if workdir and Path(workdir).exists():
        shutil.rmtree(workdir, ignore_errors=True)
    st.session_state.clear()


# ---------------------------------------------------------------------------
# Tab 1: build a video from scratch (storyboard + images + narration)
# ---------------------------------------------------------------------------

def render_build_tab() -> None:
    project_dir = _workdir() / "project"

    with st.expander("⏱️ Zaman damgası yoksa: Whisper ile otomatik hizala (opsiyonel)"):
        st.caption(
            "Cümlelerin `start`/`end` süresi yoksa, sadece `duration` içeren bir storyboard ve ses "
            "dosyası vererek otomatik zaman damgası üretebilirsin. `faster-whisper` kurulu olmalı "
            "(`pip install -r requirements-whisper.txt`). Otomatik hizalama kusursuz değildir, "
            "üretilen dosyayı kullanmadan önce kontrol et."
        )
        untimed_file = st.file_uploader("Zamansız storyboard (duration alanlı JSON)", type="json", key="untimed_sb")
        align_audio_file = st.file_uploader("Ses dosyası", type=["mp3", "wav", "m4a"], key="align_audio")
        col1, col2 = st.columns(2)
        language = col1.text_input("Dil kodu", value="tr")
        model_size = col2.selectbox("Whisper model boyutu", ["tiny", "base", "small", "medium"], index=2)
        if st.button("Hizala"):
            if not untimed_file or not align_audio_file:
                st.warning("Hem storyboard hem ses dosyası gerekli.")
            else:
                align_dir = _workdir() / "align"
                align_dir.mkdir(parents=True, exist_ok=True)
                untimed_path = _save_upload(untimed_file, align_dir / "untimed_storyboard.json")
                audio_path = _save_upload(align_audio_file, align_dir / align_audio_file.name)
                try:
                    with st.spinner("Whisper ile hizalanıyor..."):
                        storyboard = load_storyboard(untimed_path)
                        aligned, diagnostics = align_storyboard(
                            storyboard, audio_path, model_size=model_size, language=language
                        )
                    output_path = align_dir / "storyboard.aligned.json"
                    save_storyboard(aligned, output_path)
                    review_count = sum(item["status"] == "review" for item in diagnostics)
                    st.success(f"Hizalama tamam. {review_count}/{len(diagnostics)} sahne elle kontrol gerektiriyor.")
                    st.dataframe(diagnostics, use_container_width=True)
                    st.download_button(
                        "Hizalanmış storyboard.json indir",
                        data=output_path.read_bytes(),
                        file_name="storyboard.aligned.json",
                        mime="application/json",
                    )
                except RuntimeError as exc:
                    st.error(str(exc))
                except CommandError as exc:
                    st.error(f"FFmpeg hatası: {exc}")

    st.subheader("1. Proje dosyaları")
    col1, col2 = st.columns(2)
    storyboard_file = col1.file_uploader("storyboard.json", type="json", key="storyboard_upload")
    audio_file = col2.file_uploader("Anlatım sesi", type=["mp3", "wav", "m4a"], key="audio_upload")

    image_mode = st.radio("Görseller", ["Tek tek yükle", "ZIP olarak yükle"], horizontal=True)
    images_dir = project_dir / "images"
    if image_mode == "Tek tek yükle":
        image_files = st.file_uploader(
            "Görseller (storyboard'daki 'image' alanıyla aynı dosya adında olmalı)",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            key="images_upload",
        )
        if image_files:
            for image_file in image_files:
                _save_upload(image_file, images_dir / image_file.name)
    else:
        images_zip = st.file_uploader("images.zip", type="zip", key="images_zip_upload")
        if images_zip is not None:
            fingerprint = (images_zip.name, images_zip.size)
            if st.session_state.get("images_zip_fp") != fingerprint:
                _extract_images_zip(images_zip, images_dir)
                st.session_state["images_zip_fp"] = fingerprint

    music_file = st.file_uploader("Arka plan müziği (opsiyonel)", type=["mp3", "wav", "m4a"], key="music_upload")

    storyboard_path = _persist_upload(storyboard_file, project_dir / "storyboard.json", "storyboard_path")
    audio_path = _persist_upload(audio_file, project_dir / ("audio_" + (audio_file.name if audio_file else "")), "audio_path")
    music_path = _persist_upload(music_file, project_dir / ("music_" + (music_file.name if music_file else "")), "music_path")

    if not (storyboard_path and audio_path and images_dir.exists() and any(images_dir.iterdir())):
        st.info("Devam etmek için storyboard.json, ses ve en az bir görsel yükle.")
        return

    try:
        storyboard: Storyboard = load_storyboard(storyboard_path)
    except Exception as exc:
        st.error(f"Storyboard okunamadı: {exc}")
        return

    st.subheader("2. Doğrulama")
    try:
        audio_duration = probe_duration(audio_path)
    except CommandError as exc:
        st.error(f"Ses dosyası okunamadı: {exc}")
        return
    issues = validate_storyboard(storyboard, images_dir, audio_duration)
    errors, warnings = summarize_issues(issues)
    if issues:
        with st.expander(f"Doğrulama sonucu: {errors} hata, {warnings} uyarı", expanded=bool(errors)):
            for issue in issues:
                icon = "❌" if issue.level == "error" else "⚠️"
                scene = f" [sahne {issue.scene_id}]" if issue.scene_id else ""
                st.write(f"{icon} `{issue.code}`{scene}: {issue.message}")
    else:
        st.success("Storyboard sorunsuz görünüyor.")

    st.subheader("3. Render aralığı")
    scene_labels = [f"{scene.id} — {scene.sentence[:40] or scene.image}" for scene in storyboard.scenes]
    scene_ids = [scene.id for scene in storyboard.scenes]
    range_mode = st.checkbox("Sadece belirli sahneler arası render et", value=False)
    start_id: str | None = None
    end_id: str | None = None
    if range_mode:
        col1, col2 = st.columns(2)
        start_choice = col1.selectbox("Başlangıç sahnesi", scene_labels, index=0)
        end_choice = col2.selectbox("Bitiş sahnesi", scene_labels, index=len(scene_labels) - 1)
        start_id = scene_ids[scene_labels.index(start_choice)]
        end_id = scene_ids[scene_labels.index(end_choice)]
        if scene_ids.index(start_id) > scene_ids.index(end_id):
            st.error("Başlangıç sahnesi bitiş sahnesinden sonra olamaz.")
            return
    else:
        st.caption("Baştan sona, tüm storyboard render edilecek.")

    st.subheader("4. Kalite")
    quality = st.radio(
        "Çözünürlük", ["Preview (960x540, hızlı)", "1080p Final"], horizontal=True, key="build_quality"
    )
    preview = quality.startswith("Preview")

    with st.expander("Gelişmiş ayarlar"):
        col1, col2, col3 = st.columns(3)
        transition = col1.selectbox("Geçiş", TRANSITIONS, index=TRANSITIONS.index("fade"))
        transition_duration = col2.number_input("Geçiş süresi (sn)", value=0.35, min_value=0.0, step=0.05)
        crf = col3.number_input("CRF (düşük = yüksek kalite)", value=18, min_value=0, max_value=51)
        col4, col5 = st.columns(2)
        music_volume = col4.slider("Müzik seviyesi", 0.0, 1.0, 0.08)
        narration_volume = col5.slider("Anlatım seviyesi", 0.0, 2.0, 1.0)

    if st.button("🎬 Render et", type="primary"):
        settings = RenderSettings(
            transition=transition,
            transition_duration=transition_duration,
            crf=int(crf),
            music_volume=music_volume,
            narration_volume=narration_volume,
            preview=preview,
            cache_dir=_workdir() / ".cache" / "scenes",
        )
        output_path = _workdir() / "output" / "build_output.mp4"
        try:
            with st.spinner("Render ediliyor... (uzun videolarda biraz sürebilir)"):
                build_video_range(
                    storyboard,
                    images_dir,
                    audio_path,
                    output_path,
                    settings,
                    start_scene_id=start_id,
                    end_scene_id=end_id,
                    music=music_path if music_path and Path(music_path).is_file() else None,
                )
            st.success("Video hazır!")
            st.video(str(output_path))
            st.download_button(
                "Videoyu indir", data=output_path.read_bytes(), file_name="video.mp4", mime="video/mp4"
            )
        except CommandError as exc:
            st.error(f"FFmpeg hatası:\n{exc}")
        except Exception as exc:
            st.error(f"Render başarısız: {exc}")


# ---------------------------------------------------------------------------
# Tab 2: add zoom/pan to an existing video
# ---------------------------------------------------------------------------

def render_motion_tab() -> None:
    st.subheader("1. Video yükle")
    video_file = st.file_uploader("Video dosyası", type=["mp4", "mov", "mkv", "webm"], key="motion_video_upload")
    video_path = _persist_upload(
        video_file, _workdir() / "motion" / ("input_" + (video_file.name if video_file else "")), "motion_video_path"
    )
    if not video_path:
        st.info("Devam etmek için bir video yükle.")
        return

    try:
        info = probe_video_info(video_path)
    except CommandError as exc:
        st.error(f"Video okunamadı: {exc}")
        return
    st.caption(
        f"{info.width}×{info.height}, {info.fps:.2f} fps, {info.duration:.1f}s"
        f"{' (ses var)' if info.has_audio else ' (ses yok)'}"
    )

    st.subheader("2. Statik bölüm tespiti")
    col1, col2, col3 = st.columns(3)
    threshold = col1.slider(
        "Hassasiyet (eşik)", 0.001, 0.05, 0.012, 0.001,
        help="Düşük değer = daha az sahne 'statik' sayılır, daha katı.",
    )
    min_duration = col2.slider("Minimum sahne süresi (sn)", 1.0, 10.0, 2.5, 0.5)
    sample_fps = col3.slider("Örnekleme fps", 2.0, 15.0, 6.0, 1.0)
    default_zoom = st.slider("Varsayılan zoom miktarı", 1.0, 1.25, 1.12, 0.01)
    motions = st.multiselect(
        "Sırayla uygulanacak efektler", sorted(APPLICABLE_MOTIONS), default=MOTION_ROTATION
    )

    if st.button("🔍 Statik Bölümleri Tespit Et"):
        try:
            with st.spinner("Video taranıyor..."):
                segments = detect_static_segments(
                    video_path,
                    threshold=threshold,
                    min_duration=min_duration,
                    sample_fps=sample_fps,
                    motions=motions or None,
                    zoom=default_zoom,
                )
            st.session_state["motion_segments"] = [
                {
                    "start": s.start,
                    "end": s.end,
                    "motion": s.motion,
                    "zoom": s.zoom,
                    "focus_x": s.focus_x,
                    "focus_y": s.focus_y,
                }
                for s in segments
            ]
            if not segments:
                st.warning("Statik bölüm bulunamadı. Eşiği veya minimum süreyi düşürüp tekrar dene.")
            else:
                st.success(f"{len(segments)} statik bölüm bulundu.")
        except CommandError as exc:
            st.error(f"FFmpeg hatası: {exc}")

    if "motion_segments" not in st.session_state:
        return

    st.subheader("3. Bölümleri gözden geçir / düzenle")
    st.caption(
        "İstemediğin bir satırı silebilir, `motion`/`zoom`/`focus_x`/`focus_y` değerlerini değiştirebilir "
        "ya da elle yeni bir satır ekleyebilirsin. Zoom-out gerçek görüntüde zaten var olanı zamanla geri "
        "açar; kareler dışına yeni içerik ekleyemez."
    )
    edited = st.data_editor(
        st.session_state["motion_segments"],
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "start": st.column_config.NumberColumn("Başlangıç (sn)", min_value=0.0, format="%.2f"),
            "end": st.column_config.NumberColumn("Bitiş (sn)", min_value=0.0, format="%.2f"),
            "motion": st.column_config.SelectboxColumn("Hareket", options=sorted(APPLICABLE_MOTIONS)),
            "zoom": st.column_config.NumberColumn("Zoom", min_value=1.0, max_value=1.25, step=0.01, format="%.2f"),
            "focus_x": st.column_config.NumberColumn("Odak X", min_value=0.0, max_value=1.0, step=0.05, format="%.2f"),
            "focus_y": st.column_config.NumberColumn("Odak Y", min_value=0.0, max_value=1.0, step=0.05, format="%.2f"),
        },
        key="motion_segments_editor",
    )

    st.subheader("4. Kalite ve çözünürlük")
    quality = st.radio(
        "Render kalitesi", ["Final (yüksek kalite)", "Preview (hızlı, düşük kalite)"],
        horizontal=True, key="motion_quality",
    )
    crf, preset = (30, "veryfast") if quality.startswith("Preview") else (18, "medium")

    scale_labels = {
        "1x (kaynakla aynı)": 1.0,
        "1.5x büyüt": 1.5,
        "2x büyüt": 2.0,
    }
    scale_choice = st.radio(
        "Çıkış çözünürlüğü", list(scale_labels), horizontal=True, key="motion_upscale",
        help="FFmpeg'in lanczos filtresiyle piksel sayısını artırır. Gerçek yeni detay eklemez, "
        "sadece büyütüp pürüzsüzleştirir — kaynağın kendisi düşük çözünürlükse görüntü yine de net olmaz.",
    )
    scale_factor = scale_labels[scale_choice]
    target_width = int(round(info.width * scale_factor / 2)) * 2
    target_height = int(round(info.height * scale_factor / 2)) * 2
    if scale_factor == 1.0:
        st.caption(f"Video {info.width}×{info.height} çözünürlükte kalacak.")
    else:
        st.caption(f"Video {info.width}×{info.height} → {target_width}×{target_height} olarak büyütülecek.")

    if st.button("🎬 Efekti Uygula ve Render Et", type="primary"):
        try:
            segments = [
                MotionSegment(
                    start=float(row["start"]),
                    end=float(row["end"]),
                    motion=str(row["motion"]),
                    zoom=float(row["zoom"]),
                    focus_x=float(row["focus_x"]),
                    focus_y=float(row["focus_y"]),
                )
                for row in edited
            ]
        except (KeyError, TypeError, ValueError) as exc:
            st.error(f"Segment tablosu geçersiz: {exc}")
            return

        output_path = _workdir() / "output" / "motion_output.mp4"
        progress_bar = st.progress(0.0)
        status_text = st.empty()
        start_time = time.time()

        def _on_progress(fraction: float) -> None:
            elapsed = time.time() - start_time
            percent = int(fraction * 100)
            if fraction >= 0.999:
                status_text.text(f"%{percent} — tamamlandı ({_format_eta(elapsed)})")
            elif fraction > 0.02:
                eta = elapsed / fraction - elapsed
                status_text.text(f"%{percent} — kalan süre ~{_format_eta(eta)}")
            else:
                status_text.text(f"%{percent} — kalan süre hesaplanıyor...")
            progress_bar.progress(min(fraction, 1.0))

        try:
            apply_motion_segments(
                video_path,
                segments,
                output_path,
                crf=crf,
                preset=preset,
                target_width=target_width if scale_factor != 1.0 else None,
                target_height=target_height if scale_factor != 1.0 else None,
                on_progress=_on_progress,
            )
            st.success("Video hazır!")
            st.video(str(output_path))
            st.download_button(
                "Videoyu indir", data=output_path.read_bytes(), file_name="video_with_motion.mp4", mime="video/mp4"
            )
        except ValueError as exc:
            st.error(str(exc))
        except CommandError as exc:
            st.error(f"FFmpeg hatası:\n{exc}")


# ---------------------------------------------------------------------------
# Tab 3: smooth a choppy render and optionally upscale/denoise/sharpen it
# ---------------------------------------------------------------------------

def render_enhance_tab() -> None:
    st.subheader("1. Video yükle")
    video_file = st.file_uploader("Video dosyası (mp4)", type=["mp4"], key="enhance_video_upload")
    video_path = _persist_upload(
        video_file, _workdir() / "enhance" / ("input_" + (video_file.name if video_file else "")), "enhance_video_path"
    )
    if not video_path:
        st.info("Devam etmek için bir mp4 video yükle (örn. After Effects'ten dışa aktarılmış, takılan/kesik bir render).")
        return

    try:
        info = probe_video_info(video_path)
    except CommandError as exc:
        st.error(f"Video okunamadı: {exc}")
        return
    st.caption(
        f"{info.width}×{info.height}, {info.fps:.2f} fps, {info.duration:.1f}s"
        f"{' (ses var)' if info.has_audio else ' (ses yok)'}"
    )

    st.subheader("2. Akıcılık (kare hızını artırarak)")
    smooth_on = st.checkbox("Kare hızını artırarak akıcılaştır", value=True, key="enhance_smooth_on")
    target_fps: float | None = None
    interpolation = "blend"
    if smooth_on:
        candidate_fps = sorted({fps for fps in (30.0, 50.0, 60.0, round(info.fps * 2, 2)) if fps > info.fps})
        if not candidate_fps:
            st.caption(f"Video zaten {info.fps:.2f} fps — daha da artırmak için hedef değer bulunamadı.")
            smooth_on = False
        else:
            target_fps = st.select_slider(
                "Hedef kare hızı (fps)", options=candidate_fps, value=candidate_fps[-1], key="enhance_target_fps"
            )
            method_choice = st.radio(
                "Yöntem",
                ["Güvenli (karışım/blend, önerilen)", "Hareket telafili (en pürüzsüz, titremeye açık)"],
                horizontal=True,
                key="enhance_interp_method",
            )
            interpolation = "blend" if method_choice.startswith("Güvenli") else "mci"
            st.caption(
                "After Effects gibi vektör/motion-graphic render'larda hareket telafili yöntem "
                "kareler arası titreme/dalgalanma yapabilir (yanlış hareket vektörü tahmini yüzünden). "
                "Bu yüzden varsayılan 'Güvenli' — gerçek kamera görüntüsü işliyorsan hareket telafilini deneyebilirsin."
            )

    st.subheader("3. Kalite iyileştirme (opsiyonel)")
    col1, col2 = st.columns(2)
    denoise = col1.checkbox("Gürültü azalt (denoise)", key="enhance_denoise")
    sharpen = col2.checkbox("Netleştir (sharpen)", key="enhance_sharpen")

    scale_labels = {"1x (kaynakla aynı)": 1.0, "1.5x büyüt": 1.5, "2x büyüt": 2.0}
    scale_choice = st.radio("Çözünürlük", list(scale_labels), horizontal=True, key="enhance_upscale")
    scale_factor = scale_labels[scale_choice]
    if scale_factor == 1.0:
        st.caption(f"Video {info.width}×{info.height} çözünürlükte kalacak.")
    else:
        target_w = int(round(info.width * scale_factor / 2)) * 2
        target_h = int(round(info.height * scale_factor / 2)) * 2
        st.caption(
            f"Video {info.width}×{info.height} → {target_w}×{target_h} olarak büyütülecek. "
            "FFmpeg'in lanczos filtresiyle büyütür; gerçek yeni detay eklemez, sadece pürüzsüzleştirir."
        )

    st.subheader("4. Kodlama kalitesi")
    quality = st.radio(
        "Render kalitesi", ["Final (yüksek kalite)", "Preview (hızlı, düşük kalite)"],
        horizontal=True, key="enhance_quality",
    )
    crf, preset = (30, "veryfast") if quality.startswith("Preview") else (18, "medium")

    if not (smooth_on or denoise or sharpen or scale_factor != 1.0):
        st.info("Devam etmek için akıcılaştırma, gürültü azaltma, netleştirme ya da büyütmeden en az birini seç.")
        return

    if st.button("✨ İşle", type="primary"):
        output_path = _workdir() / "output" / "enhanced_output.mp4"
        progress_bar = st.progress(0.0)
        status_text = st.empty()
        start_time = time.time()

        def _on_progress(fraction: float) -> None:
            elapsed = time.time() - start_time
            percent = int(fraction * 100)
            if fraction >= 0.999:
                status_text.text(f"%{percent} — tamamlandı ({_format_eta(elapsed)})")
            elif fraction > 0.02:
                eta = elapsed / fraction - elapsed
                status_text.text(f"%{percent} — kalan süre ~{_format_eta(eta)}")
            else:
                status_text.text(f"%{percent} — kalan süre hesaplanıyor...")
            progress_bar.progress(min(fraction, 1.0))

        try:
            enhance_video(
                video_path,
                output_path,
                target_fps=target_fps if smooth_on else None,
                interpolation=interpolation,
                upscale_factor=scale_factor,
                denoise=denoise,
                sharpen=sharpen,
                crf=crf,
                preset=preset,
                on_progress=_on_progress,
            )
            st.success("Video hazır!")
            st.video(str(output_path))
            st.download_button(
                "Videoyu indir", data=output_path.read_bytes(), file_name="video_enhanced.mp4", mime="video/mp4"
            )
        except ValueError as exc:
            st.error(str(exc))
        except CommandError as exc:
            st.error(f"FFmpeg hatası:\n{exc}")


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

st.title("🎬 Mitoloji Video Stüdyosu")

ready, ffmpeg_error = _ffmpeg_ready()
if not ready:
    st.error(f"FFmpeg bulunamadı: {ffmpeg_error}\nBu araç çalışmadan önce FFmpeg kurulmalı ve PATH'e eklenmelidir.")
    st.stop()

with st.sidebar:
    st.header("Mod")
    mode = st.radio(
        "Ne yapmak istiyorsun?",
        [
            "Sıfırdan video oluştur",
            "Var olan videoya zoom/pan ekle",
            "Videoyu akıcılaştır / kalite artır",
        ],
        label_visibility="collapsed",
    )
    st.divider()
    if st.button("🗑️ Oturumu temizle / yeniden başla"):
        _reset_session()
        st.rerun()

if mode == "Sıfırdan video oluştur":
    render_build_tab()
elif mode == "Var olan videoya zoom/pan ekle":
    render_motion_tab()
else:
    render_enhance_tab()
