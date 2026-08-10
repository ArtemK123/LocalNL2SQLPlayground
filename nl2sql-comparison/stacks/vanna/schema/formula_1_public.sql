--
-- PostgreSQL database dump
--

\restrict 4qApKCmmYviTaM75U4yfUobbNd6Sdhesv916HzS1bfXoYLAtuL3VLRFhR3GIUZO

-- Dumped from database version 16.13
-- Dumped by pg_dump version 16.13

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: bird
--

CREATE SCHEMA public;


ALTER SCHEMA public OWNER TO bird;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: circuits; Type: TABLE; Schema: public; Owner: xiaolongli
--

CREATE TABLE public.circuits (
    circuitid bigint NOT NULL,
    circuitref text DEFAULT ''::text,
    name text DEFAULT ''::text,
    location text,
    country text,
    lat real,
    lng real,
    alt bigint,
    url text DEFAULT ''::text
);


ALTER TABLE public.circuits OWNER TO xiaolongli;

--
-- Name: circuits_circuitid_seq; Type: SEQUENCE; Schema: public; Owner: xiaolongli
--

CREATE SEQUENCE public.circuits_circuitid_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.circuits_circuitid_seq OWNER TO xiaolongli;

--
-- Name: circuits_circuitid_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xiaolongli
--

ALTER SEQUENCE public.circuits_circuitid_seq OWNED BY public.circuits.circuitid;


--
-- Name: constructorresults; Type: TABLE; Schema: public; Owner: xiaolongli
--

CREATE TABLE public.constructorresults (
    constructorresultsid bigint NOT NULL,
    raceid bigint DEFAULT '0'::bigint,
    constructorid bigint DEFAULT '0'::bigint,
    points real,
    status text
);


ALTER TABLE public.constructorresults OWNER TO xiaolongli;

--
-- Name: constructorresults_constructorresultsid_seq; Type: SEQUENCE; Schema: public; Owner: xiaolongli
--

CREATE SEQUENCE public.constructorresults_constructorresultsid_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.constructorresults_constructorresultsid_seq OWNER TO xiaolongli;

--
-- Name: constructorresults_constructorresultsid_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xiaolongli
--

ALTER SEQUENCE public.constructorresults_constructorresultsid_seq OWNED BY public.constructorresults.constructorresultsid;


--
-- Name: constructors; Type: TABLE; Schema: public; Owner: xiaolongli
--

CREATE TABLE public.constructors (
    constructorid bigint NOT NULL,
    constructorref text DEFAULT ''::text,
    name text DEFAULT ''::text,
    nationality text,
    url text DEFAULT ''::text
);


ALTER TABLE public.constructors OWNER TO xiaolongli;

--
-- Name: constructors_constructorid_seq; Type: SEQUENCE; Schema: public; Owner: xiaolongli
--

CREATE SEQUENCE public.constructors_constructorid_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.constructors_constructorid_seq OWNER TO xiaolongli;

--
-- Name: constructors_constructorid_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xiaolongli
--

ALTER SEQUENCE public.constructors_constructorid_seq OWNED BY public.constructors.constructorid;


--
-- Name: constructorstandings; Type: TABLE; Schema: public; Owner: xiaolongli
--

CREATE TABLE public.constructorstandings (
    constructorstandingsid bigint NOT NULL,
    raceid bigint DEFAULT '0'::bigint,
    constructorid bigint DEFAULT '0'::bigint,
    points real DEFAULT '0'::real,
    "position" bigint,
    positiontext text,
    wins bigint DEFAULT '0'::bigint
);


ALTER TABLE public.constructorstandings OWNER TO xiaolongli;

--
-- Name: constructorstandings_constructorstandingsid_seq; Type: SEQUENCE; Schema: public; Owner: xiaolongli
--

CREATE SEQUENCE public.constructorstandings_constructorstandingsid_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.constructorstandings_constructorstandingsid_seq OWNER TO xiaolongli;

--
-- Name: constructorstandings_constructorstandingsid_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xiaolongli
--

ALTER SEQUENCE public.constructorstandings_constructorstandingsid_seq OWNED BY public.constructorstandings.constructorstandingsid;


--
-- Name: drivers; Type: TABLE; Schema: public; Owner: xiaolongli
--

CREATE TABLE public.drivers (
    driverid bigint NOT NULL,
    driverref text DEFAULT ''::text,
    number bigint,
    code text,
    forename text DEFAULT ''::text,
    surname text DEFAULT ''::text,
    dob date,
    nationality text,
    url text DEFAULT ''::text
);


ALTER TABLE public.drivers OWNER TO xiaolongli;

--
-- Name: drivers_driverid_seq; Type: SEQUENCE; Schema: public; Owner: xiaolongli
--

CREATE SEQUENCE public.drivers_driverid_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.drivers_driverid_seq OWNER TO xiaolongli;

--
-- Name: drivers_driverid_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xiaolongli
--

ALTER SEQUENCE public.drivers_driverid_seq OWNED BY public.drivers.driverid;


--
-- Name: driverstandings; Type: TABLE; Schema: public; Owner: xiaolongli
--

CREATE TABLE public.driverstandings (
    driverstandingsid bigint NOT NULL,
    raceid bigint DEFAULT '0'::bigint,
    driverid bigint DEFAULT '0'::bigint,
    points real DEFAULT '0'::real,
    "position" bigint,
    positiontext text,
    wins bigint DEFAULT '0'::bigint
);


ALTER TABLE public.driverstandings OWNER TO xiaolongli;

--
-- Name: driverstandings_driverstandingsid_seq; Type: SEQUENCE; Schema: public; Owner: xiaolongli
--

CREATE SEQUENCE public.driverstandings_driverstandingsid_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.driverstandings_driverstandingsid_seq OWNER TO xiaolongli;

--
-- Name: driverstandings_driverstandingsid_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xiaolongli
--

ALTER SEQUENCE public.driverstandings_driverstandingsid_seq OWNED BY public.driverstandings.driverstandingsid;


--
-- Name: laptimes; Type: TABLE; Schema: public; Owner: xiaolongli
--

CREATE TABLE public.laptimes (
    raceid bigint NOT NULL,
    driverid bigint NOT NULL,
    lap bigint NOT NULL,
    "position" bigint,
    "time" text,
    milliseconds bigint
);


ALTER TABLE public.laptimes OWNER TO xiaolongli;

--
-- Name: pitstops; Type: TABLE; Schema: public; Owner: xiaolongli
--

CREATE TABLE public.pitstops (
    raceid bigint NOT NULL,
    driverid bigint NOT NULL,
    stop bigint NOT NULL,
    lap bigint,
    "time" text,
    duration text,
    milliseconds bigint
);


ALTER TABLE public.pitstops OWNER TO xiaolongli;

--
-- Name: qualifying; Type: TABLE; Schema: public; Owner: xiaolongli
--

CREATE TABLE public.qualifying (
    qualifyid bigint NOT NULL,
    raceid bigint DEFAULT '0'::bigint,
    driverid bigint DEFAULT '0'::bigint,
    constructorid bigint DEFAULT '0'::bigint,
    number bigint DEFAULT '0'::bigint,
    "position" bigint,
    q1 text,
    q2 text,
    q3 text
);


ALTER TABLE public.qualifying OWNER TO xiaolongli;

--
-- Name: qualifying_qualifyid_seq; Type: SEQUENCE; Schema: public; Owner: xiaolongli
--

CREATE SEQUENCE public.qualifying_qualifyid_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.qualifying_qualifyid_seq OWNER TO xiaolongli;

--
-- Name: qualifying_qualifyid_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xiaolongli
--

ALTER SEQUENCE public.qualifying_qualifyid_seq OWNED BY public.qualifying.qualifyid;


--
-- Name: races; Type: TABLE; Schema: public; Owner: xiaolongli
--

CREATE TABLE public.races (
    raceid bigint NOT NULL,
    year bigint DEFAULT '0'::bigint,
    round bigint DEFAULT '0'::bigint,
    circuitid bigint DEFAULT '0'::bigint,
    name text DEFAULT ''::text,
    date date,
    "time" text,
    url text
);


ALTER TABLE public.races OWNER TO xiaolongli;

--
-- Name: races_raceid_seq; Type: SEQUENCE; Schema: public; Owner: xiaolongli
--

CREATE SEQUENCE public.races_raceid_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.races_raceid_seq OWNER TO xiaolongli;

--
-- Name: races_raceid_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xiaolongli
--

ALTER SEQUENCE public.races_raceid_seq OWNED BY public.races.raceid;


--
-- Name: results; Type: TABLE; Schema: public; Owner: xiaolongli
--

CREATE TABLE public.results (
    resultid bigint NOT NULL,
    raceid bigint DEFAULT '0'::bigint,
    driverid bigint DEFAULT '0'::bigint,
    constructorid bigint DEFAULT '0'::bigint,
    number bigint,
    grid bigint DEFAULT '0'::bigint,
    "position" bigint,
    positiontext text DEFAULT ''::text,
    positionorder bigint DEFAULT '0'::bigint,
    points real DEFAULT '0'::real,
    laps bigint DEFAULT '0'::bigint,
    "time" text,
    milliseconds bigint,
    fastestlap bigint,
    rank bigint DEFAULT '0'::bigint,
    fastestlaptime text,
    fastestlapspeed text,
    statusid bigint DEFAULT '0'::bigint
);


ALTER TABLE public.results OWNER TO xiaolongli;

--
-- Name: results_resultid_seq; Type: SEQUENCE; Schema: public; Owner: xiaolongli
--

CREATE SEQUENCE public.results_resultid_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.results_resultid_seq OWNER TO xiaolongli;

--
-- Name: results_resultid_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xiaolongli
--

ALTER SEQUENCE public.results_resultid_seq OWNED BY public.results.resultid;


--
-- Name: seasons; Type: TABLE; Schema: public; Owner: xiaolongli
--

CREATE TABLE public.seasons (
    year bigint DEFAULT '0'::bigint NOT NULL,
    url text DEFAULT ''::text
);


ALTER TABLE public.seasons OWNER TO xiaolongli;

--
-- Name: status; Type: TABLE; Schema: public; Owner: xiaolongli
--

CREATE TABLE public.status (
    statusid bigint NOT NULL,
    status text DEFAULT ''::text
);


ALTER TABLE public.status OWNER TO xiaolongli;

--
-- Name: status_statusid_seq; Type: SEQUENCE; Schema: public; Owner: xiaolongli
--

CREATE SEQUENCE public.status_statusid_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.status_statusid_seq OWNER TO xiaolongli;

--
-- Name: status_statusid_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: xiaolongli
--

ALTER SEQUENCE public.status_statusid_seq OWNED BY public.status.statusid;


--
-- Name: circuits circuitid; Type: DEFAULT; Schema: public; Owner: xiaolongli
--

ALTER TABLE ONLY public.circuits ALTER COLUMN circuitid SET DEFAULT nextval('public.circuits_circuitid_seq'::regclass);


--
-- Name: constructorresults constructorresultsid; Type: DEFAULT; Schema: public; Owner: xiaolongli
--

ALTER TABLE ONLY public.constructorresults ALTER COLUMN constructorresultsid SET DEFAULT nextval('public.constructorresults_constructorresultsid_seq'::regclass);


--
-- Name: constructors constructorid; Type: DEFAULT; Schema: public; Owner: xiaolongli
--

ALTER TABLE ONLY public.constructors ALTER COLUMN constructorid SET DEFAULT nextval('public.constructors_constructorid_seq'::regclass);


--
-- Name: constructorstandings constructorstandingsid; Type: DEFAULT; Schema: public; Owner: xiaolongli
--

ALTER TABLE ONLY public.constructorstandings ALTER COLUMN constructorstandingsid SET DEFAULT nextval('public.constructorstandings_constructorstandingsid_seq'::regclass);


--
-- Name: drivers driverid; Type: DEFAULT; Schema: public; Owner: xiaolongli
--

ALTER TABLE ONLY public.drivers ALTER COLUMN driverid SET DEFAULT nextval('public.drivers_driverid_seq'::regclass);


--
-- Name: driverstandings driverstandingsid; Type: DEFAULT; Schema: public; Owner: xiaolongli
--

ALTER TABLE ONLY public.driverstandings ALTER COLUMN driverstandingsid SET DEFAULT nextval('public.driverstandings_driverstandingsid_seq'::regclass);


--
-- Name: qualifying qualifyid; Type: DEFAULT; Schema: public; Owner: xiaolongli
--

ALTER TABLE ONLY public.qualifying ALTER COLUMN qualifyid SET DEFAULT nextval('public.qualifying_qualifyid_seq'::regclass);


--
-- Name: races raceid; Type: DEFAULT; Schema: public; Owner: xiaolongli
--

ALTER TABLE ONLY public.races ALTER COLUMN raceid SET DEFAULT nextval('public.races_raceid_seq'::regclass);


--
-- Name: results resultid; Type: DEFAULT; Schema: public; Owner: xiaolongli
--

ALTER TABLE ONLY public.results ALTER COLUMN resultid SET DEFAULT nextval('public.results_resultid_seq'::regclass);


--
-- Name: status statusid; Type: DEFAULT; Schema: public; Owner: xiaolongli
--

ALTER TABLE ONLY public.status ALTER COLUMN statusid SET DEFAULT nextval('public.status_statusid_seq'::regclass);


--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: bird
--

REVOKE USAGE ON SCHEMA public FROM PUBLIC;
GRANT ALL ON SCHEMA public TO PUBLIC;
GRANT ALL ON SCHEMA public TO olap;
GRANT USAGE ON SCHEMA public TO nl2sql_ro;


--
-- Name: TABLE circuits; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON TABLE public.circuits TO nl2sql_ro;


--
-- Name: SEQUENCE circuits_circuitid_seq; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON SEQUENCE public.circuits_circuitid_seq TO nl2sql_ro;


--
-- Name: TABLE constructorresults; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON TABLE public.constructorresults TO nl2sql_ro;


--
-- Name: SEQUENCE constructorresults_constructorresultsid_seq; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON SEQUENCE public.constructorresults_constructorresultsid_seq TO nl2sql_ro;


--
-- Name: TABLE constructors; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON TABLE public.constructors TO nl2sql_ro;


--
-- Name: SEQUENCE constructors_constructorid_seq; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON SEQUENCE public.constructors_constructorid_seq TO nl2sql_ro;


--
-- Name: TABLE constructorstandings; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON TABLE public.constructorstandings TO nl2sql_ro;


--
-- Name: SEQUENCE constructorstandings_constructorstandingsid_seq; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON SEQUENCE public.constructorstandings_constructorstandingsid_seq TO nl2sql_ro;


--
-- Name: TABLE drivers; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON TABLE public.drivers TO nl2sql_ro;


--
-- Name: SEQUENCE drivers_driverid_seq; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON SEQUENCE public.drivers_driverid_seq TO nl2sql_ro;


--
-- Name: TABLE driverstandings; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON TABLE public.driverstandings TO nl2sql_ro;


--
-- Name: SEQUENCE driverstandings_driverstandingsid_seq; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON SEQUENCE public.driverstandings_driverstandingsid_seq TO nl2sql_ro;


--
-- Name: TABLE laptimes; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON TABLE public.laptimes TO nl2sql_ro;


--
-- Name: TABLE pitstops; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON TABLE public.pitstops TO nl2sql_ro;


--
-- Name: TABLE qualifying; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON TABLE public.qualifying TO nl2sql_ro;


--
-- Name: SEQUENCE qualifying_qualifyid_seq; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON SEQUENCE public.qualifying_qualifyid_seq TO nl2sql_ro;


--
-- Name: TABLE races; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON TABLE public.races TO nl2sql_ro;


--
-- Name: SEQUENCE races_raceid_seq; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON SEQUENCE public.races_raceid_seq TO nl2sql_ro;


--
-- Name: TABLE results; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON TABLE public.results TO nl2sql_ro;


--
-- Name: SEQUENCE results_resultid_seq; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON SEQUENCE public.results_resultid_seq TO nl2sql_ro;


--
-- Name: TABLE seasons; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON TABLE public.seasons TO nl2sql_ro;


--
-- Name: TABLE status; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON TABLE public.status TO nl2sql_ro;


--
-- Name: SEQUENCE status_statusid_seq; Type: ACL; Schema: public; Owner: xiaolongli
--

GRANT SELECT ON SEQUENCE public.status_statusid_seq TO nl2sql_ro;


--
-- Name: DEFAULT PRIVILEGES FOR SEQUENCES; Type: DEFAULT ACL; Schema: public; Owner: bird
--

ALTER DEFAULT PRIVILEGES FOR ROLE bird IN SCHEMA public GRANT SELECT ON SEQUENCES TO nl2sql_ro;


--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: public; Owner: bird
--

ALTER DEFAULT PRIVILEGES FOR ROLE bird IN SCHEMA public GRANT SELECT ON TABLES TO nl2sql_ro;


--
-- PostgreSQL database dump complete
--

\unrestrict 4qApKCmmYviTaM75U4yfUobbNd6Sdhesv916HzS1bfXoYLAtuL3VLRFhR3GIUZO

