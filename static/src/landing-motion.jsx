import React from "react";
import { createRoot } from "react-dom/client";
import { LazyMotion, domAnimation, m, useMotionValueEvent, useReducedMotion, useScroll, useSpring, useTransform } from "framer-motion";

function ScrollReveal({ target }) {
  const targetRef = React.useMemo(() => ({ current: target }), [target]);
  const reduceMotion = useReducedMotion();
  const { scrollYProgress } = useScroll({
    target: targetRef,
    offset: ["start 0.92", "end 0.55"],
  });
  const progress = useSpring(scrollYProgress, { stiffness: 130, damping: 32, mass: 0.3 });

  const updateTarget = (value) => {
    if (reduceMotion) return;
    const amount = Math.max(0, Math.min(1, value));
    target.style.opacity = String(amount);
    target.style.translate = `0 ${((1 - amount) * 16).toFixed(1)}px`;
  };

  React.useEffect(() => {
    if (reduceMotion) return undefined;
    target.style.willChange = "opacity, translate";
    const frame = requestAnimationFrame(() => updateTarget(progress.get()));
    return () => {
      cancelAnimationFrame(frame);
      target.style.removeProperty("opacity");
      target.style.removeProperty("translate");
      target.style.removeProperty("will-change");
    };
  }, [target, progress, reduceMotion]);

  useMotionValueEvent(progress, "change", updateTarget);
  return null;
}

function ScrollCharacter({ character, index, count, progress }) {
  const start = 0.04 + (index / count) * 0.78;
  const end = Math.min(start + 0.2, 1);
  const opacity = useTransform(progress, [start, end], [0, 1]);
  const y = useTransform(progress, [start, end], [7, 0]);

  return (
    <m.span aria-hidden="true" style={{ display: "inline-block", opacity, y }}>
      {character}
    </m.span>
  );
}

function AnimatedNumber({ element }) {
  const ref = React.useRef(null);
  const reduceMotion = useReducedMotion();
  const value = Number(element.dataset.value || 0);
  const decimals = Number(element.dataset.decimals || 0);
  const suffix = element.dataset.suffix || "";
  const prefix = element.dataset.prefix || "";
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start 0.92", "end 0.42"],
  });
  const progress = useSpring(scrollYProgress, { stiffness: 150, damping: 34, mass: 0.25 });
  const number = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
  const text = `${prefix}${number}${suffix}`;

  if (reduceMotion) return <span>{text}</span>;

  return (
    <LazyMotion features={domAnimation}>
    <m.span
      ref={ref}
      aria-label={text}
      style={{ display: "inline-flex", whiteSpace: "pre" }}
    >
      {[...text].map((character, index) => (
        <ScrollCharacter key={`${character}-${index}`} character={character} index={index} count={text.length} progress={progress} />
      ))}
    </m.span>
    </LazyMotion>
  );
}

function mountLandingNumbers() {
  document.querySelectorAll("[data-motion-stat]").forEach((element) => {
    const className = element.className;
    createRoot(element).render(<AnimatedNumber element={element} />);
    element.className = className;
  });

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const targets = [...document.querySelectorAll(
    ".command-grid section:not(.animate-fade-up), .command-grid article, .command-grid [data-scroll-motion]",
  )];
  if (!targets.length) return;

  targets.forEach((target) => {
    target.style.opacity = "0";
    target.style.translate = "0 16px";
  });
  const motionRoot = document.createElement("div");
  motionRoot.setAttribute("aria-hidden", "true");
  Object.assign(motionRoot.style, {
    position: "fixed",
    width: "0",
    height: "0",
    overflow: "hidden",
    pointerEvents: "none",
  });
  document.body.appendChild(motionRoot);
  createRoot(motionRoot).render(
    <>{targets.map((target, index) => <ScrollReveal key={index} target={target} />)}</>,
  );
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mountLandingNumbers, { once: true });
} else {
  mountLandingNumbers();
}
